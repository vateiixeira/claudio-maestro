import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, join, relative } from 'node:path'
import { expect, test } from './fixtures'

const STATUS = {
  installed: true, version: '0.170.0', latest: '0.171.0', can_update: true, update_available: true,
  auth: 'chatgpt', requires_auth: true, default_model: 'codex-fast', default_effort: 'low',
  usage: {
    enabled: true, plan: 'Plus', fetched_at: 1_800_000_000, error: null,
    limits: [{ kind: 'session', label: '5 horas', percent: 31, severity: 'normal', resets_at: null }],
  },
  models_refreshed: true, error: null,
}

const FAST = { value: 'codex-fast', displayName: 'Codex rápido', description: '', supportsEffort: true, supportedEffortLevels: ['low'], isDefault: true }
const DEEP = { value: 'codex-deep', displayName: 'Codex completo', description: '', supportsEffort: true, supportedEffortLevels: ['high', 'xhigh'] }

test('Codex oferece padrões próprios, conta e atualização no menu da nova conversa', async ({ page }) => {
  let preferences: Record<string, unknown> = {}
  let currentModels = [FAST]
  let version = STATUS.version

  await page.route('**/api/state', (route) => route.fulfill({ json: { preferences } }))
  await page.route('**/api/state/preferences', (route) => {
    preferences = route.request().postDataJSON()
    return route.fulfill({ json: preferences })
  })
  await page.route('**/api/providers', (route) => route.fulfill({ json: [
    { id: 'claude', name: 'Claude', enabled: true, available: true },
    { id: 'codex', name: 'Codex', enabled: preferences.codex_enabled === true, available: true },
  ] }))
  await page.route('**/api/models?provider=codex', (route) => route.fulfill({ json: currentModels }))
  await page.route('**/api/codex-cli', (route) => route.fulfill({ json: { ...STATUS, version } }))
  await page.route('**/api/codex-cli/refresh', (route) => {
    currentModels = [FAST, DEEP]
    return route.fulfill({ json: { ...STATUS, version } })
  })
  await page.route('**/api/codex-cli/update', (route) => {
    version = STATUS.latest
    return route.fulfill({ json: {
      ...STATUS, version, update_available: false, ok: true, before: STATUS.version, after: version,
      message: 'Codex atualizado.',
    } })
  })

  await page.goto('/preferencias?aba=conversas')
  await page.getByTestId('pref-codex').check()
  await expect(page.getByTestId('pref-codex-model').getByRole('button')).toHaveText('Padrão · Codex rápido')
  await page.getByTestId('codex-cli-refresh').click()
  await page.getByRole('button', { name: 'Modelo padrão do Codex' }).click()
  await page.getByRole('menuitemradio', { name: 'Codex completo' }).click()
  await page.getByRole('button', { name: 'Raciocínio padrão do Codex' }).click()
  await expect(page.getByRole('menuitemradio', { name: 'baixo', exact: true })).toHaveCount(0)
  await page.getByRole('menuitemradio', { name: 'muito alto', exact: true }).click()
  await page.getByTestId('save').click()
  await expect(page.getByTestId('saved')).toBeVisible()

  await page.getByTestId('nav-new').click()
  const modal = page.getByTestId('new-conversation-modal')
  await modal.getByTestId('nc-provider').selectOption('codex')
  await expect(modal.getByRole('button', { name: 'Modelo', exact: true })).toHaveText('Codex completo')
  await expect(modal.getByRole('button', { name: 'Raciocínio', exact: true })).toHaveText('Raciocínio muito alto')
  await modal.getByTestId('nc-close').click()
  await page.getByTestId('nav-new').click()
  await expect(modal.getByTestId('nc-provider')).toHaveValue('codex')

  await modal.getByRole('button', { name: 'Modelo', exact: true }).click()
  const footer = page.getByRole('menu', { name: 'Modelo' }).getByTestId('codex-cli-footer')
  await expect(footer).toContainText('ChatGPT Plus')
  await expect(footer.getByRole('meter')).toHaveAttribute('aria-valuenow', '31')
  await expect(footer).toContainText('0.170.0')
  await page.keyboard.press('Tab')
  await expect(footer.getByTestId('codex-cli-refresh')).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(footer.getByTestId('codex-cli-update')).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(footer.getByTestId('codex-cli-result')).toHaveText('Codex atualizado.')
  await expect(footer).toContainText('0.171.0')
})

test('uma conversa Codex recebe a resposta e mantém histórico e contexto ao reabrir', async ({ page, baseURL }) => {
  const headers = { 'X-Maestro': '1', Origin: baseURL! }
  const state = await page.request.get('/api/state', { headers })
  expect(state.ok()).toBeTruthy()
  const previous = (await state.json()).preferences ?? {}
  const response = await page.request.get('/api/projects', { headers })
  expect(response.ok()).toBeTruthy()
  const seed = ((await response.json()) as { name: string; path: string }[]).find((project) => project.name === 'Loja Demo')!
  expect(relative(tmpdir(), seed.path)).toMatch(/^maestro-e2e-[^/]+\/home\/projetos\/loja-demo$/)
  const folder = await mkdtemp(join(dirname(seed.path), 'codex-conversa-'))
  let projectId: number | undefined

  try {
    const project = await page.request.post('/api/projects', {
      headers, data: { name: 'Projeto Codex E2E', path: folder, color: '#5294a8' },
    })
    expect(project.status()).toBe(201)
    projectId = (await project.json()).id as number

    await page.goto('/preferencias?aba=conversas')
    await page.getByTestId('pref-codex').check()
    await page.getByTestId('save').click()
    await expect(page.getByTestId('saved')).toBeVisible()
    await expect(page.getByTestId('codex-usage-meter')).toContainText('Plus')
    await page.getByTestId('nav-new').click()
    const modal = page.getByTestId('new-conversation-modal')
    await modal.getByTestId('nc-project').selectOption(String(projectId))
    await modal.getByTestId('nc-provider').selectOption('codex')
    await expect(modal.getByRole('button', { name: 'Modelo', exact: true })).toHaveText('Padrão · Codex de teste')
    await modal.getByRole('button', { name: 'Modelo', exact: true }).click()
    const footer = page.getByRole('menu', { name: 'Modelo' }).getByTestId('codex-cli-footer')
    await expect(footer.getByRole('meter')).toHaveAttribute('aria-valuenow', '31')
    await footer.getByTestId('codex-cli-update').click()
    await expect(footer.getByTestId('codex-cli-result')).toContainText('atualizado para 0.173.0')
    await page.keyboard.press('Escape')
    const prompt = 'Conte os tokens desta conversa'
    await modal.getByTestId('nc-prompt').fill(prompt)
    await modal.getByTestId('nc-submit').click()

    await expect(page).toHaveURL(/\/sessions\/[^/]+$/)
    const reply = page.getByText(`Resposta do Codex de teste: ${prompt}`, { exact: true })
    await expect(reply).toBeVisible()
    const context = page.getByTestId('context-usage')
    await expect(context).toHaveText('13%')
    await context.click()
    const popover = page.getByTestId('context-popover')
    await expect(popover.getByTestId('ctx-tokens')).toHaveText('125 / 1 mil')
    await page.keyboard.press('Escape')

    await page.reload()
    await expect(reply).toBeVisible()
    await expect(context).toHaveText('13%')
    const toggle = page.getByTestId('toggle-details')
    if (await toggle.getAttribute('aria-pressed') !== 'true') await toggle.click()
    await expect(page.getByTestId('prop-provider')).toHaveText('Codex')
    await expect(page.getByTestId('codex-resume-command')).toContainText(/codex resume [\da-f-]{36}/)
  } finally {
    await page.goto('about:blank')
    const restored = await page.request.put('/api/state/preferences', { headers, data: previous })
    const removed = projectId === undefined ? undefined : await page.request.delete(`/api/projects/${projectId}`, { headers })
    await rm(folder, { recursive: true, force: true })
    expect(restored.ok()).toBeTruthy()
    if (removed) expect(removed.status()).toBe(204)
  }
})
