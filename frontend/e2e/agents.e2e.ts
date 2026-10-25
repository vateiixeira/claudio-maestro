import type { Page } from '@playwright/test'
import { expect, test } from './fixtures'

// The texts below are the "Triagem" agent of scripts/e2e_server.py (TRIAGEM_*). Notices cannot be made
// through the API, so the one test that reads them (and marks one as read) is the only one that touches them.
const SKILL_DESCRIPTION = 'Separa os chamados novos por urgência e responde os simples.'
const FAILURE_REASON = 'O token do repositório expirou.'
const ALERT_TEXT = 'A Triagem falhou nas últimas execuções.'
const SUMMARY_TEXT = 'Triagem concluída: 3 itens novos.'

let counter = 0
const uniqueName = (prefix: string) => `${prefix} ${Date.now().toString(36)}${counter++}`

test.afterEach(async ({ page, baseURL }) => {
  // Agents made by a test go away with it; the seeded "Triagem" stays.
  const headers = { 'X-Maestro': '1', Origin: baseURL! }
  const list = await page.request.get('/api/specialists', { headers })
  for (const agent of (await list.json()) as { id: number; slug: string }[]) {
    if (agent.slug !== 'triagem') await page.request.delete(`/api/specialists/${agent.id}`, { headers })
  }
})

async function createAgent(page: Page, name: string) {
  await page.goto('/agentes')
  await page.getByTestId('agent-new').click()
  await page.getByTestId('new-name').fill(name)
  await page.getByRole('dialog').getByRole('button', { name: 'Criar' }).click()
  await expect(page.getByTestId('agent-name')).toHaveText(name)
  await page.getByTestId('agent-tab-settings').click()
}

test('mostra o agente semeado com a skill, o horário e as execuções', async ({ page }) => {
  await page.goto('/agentes')
  await page.getByTestId('agent-picker-toggle').click()
  await page.getByTestId('agent-item').filter({ hasText: 'Triagem' }).click()
  await expect(page.getByTestId('agent-name')).toHaveText('Triagem')
  await page.getByTestId('agent-tab-settings').click()
  await expect(page.getByTestId('skill-text')).toHaveValue(new RegExp(SKILL_DESCRIPTION))
  await expect(page.getByTestId('schedule-row')).toHaveCount(1)
  await expect(page.getByTestId('schedule-time')).toHaveValue('03:00')
  await page.getByTestId('agent-tab-runs').click()
  const rows = page.getByTestId('run-row')
  await expect(rows).toHaveCount(2)
  await expect(rows.filter({ hasText: FAILURE_REASON })).toHaveCount(1)
})

test('cria um agente pela tela, com o identificador sugerido pelo nome', async ({ page }) => {
  const name = uniqueName('Revisor')
  await page.goto('/agentes')
  await page.getByTestId('agent-new').click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByRole('heading', { name: 'Novo agente' })).toBeVisible()
  await page.getByTestId('new-name').fill(name)
  await expect(page.getByTestId('new-slug')).toHaveValue(/^revisor-[a-z0-9]+$/)
  await dialog.getByLabel('Projeto de origem').selectOption({ label: 'Loja Demo' })
  await dialog.getByRole('button', { name: 'Criar' }).click()
  await expect(page).toHaveURL(/\/agentes\/\d+$/)
  await expect(page.getByTestId('agent-name')).toHaveText(name)
  await expect(page.getByTestId('agent-picker-toggle')).toContainText(name)
})

test('edita e salva a skill; frontmatter inválido mostra o erro sem perder o texto', async ({ page, consoleErrors }) => {
  const name = uniqueName('Skill')
  await createAgent(page, name)
  const area = page.getByTestId('skill-text')
  const save = page.getByTestId('skill-save')
  await expect(save).toBeDisabled()

  const good = `---\nname: ${name}\ndescription: Faz uma coisa de teste.\n---\n\nSiga as instruções.\n`
  await area.fill(good)
  await save.click()
  await expect(save).toBeDisabled()
  await expect(page.getByTestId('skill-error')).toHaveCount(0)
  await page.reload()
  await expect(page.getByTestId('skill-text')).toHaveValue(good)

  const bad = 'sem cabeçalho nenhum, só texto solto'
  await page.getByTestId('skill-text').fill(bad)
  await page.getByTestId('skill-save').click()
  await expect(page.getByTestId('skill-error')).toBeVisible()
  // The browser logs the refused request (422) by itself: expected here, so it does not count.
  consoleErrors.splice(0, consoleErrors.length, ...consoleErrors.filter((m) => !m.includes('status of 422')))
  await expect(page.getByTestId('skill-text')).toHaveValue(bad)
  await expect(page.getByTestId('skill-save')).toBeEnabled()
})

test('adiciona um horário e salva', async ({ page }) => {
  await createAgent(page, uniqueName('Horario'))
  await expect(page.getByTestId('schedule-row')).toHaveCount(0)
  await page.getByTestId('schedule-add').click()
  await expect(page.getByTestId('schedule-row')).toHaveCount(1)
  await page.getByTestId('schedule-time').fill('07:15')
  await page.getByTestId('schedule-save').click()
  await expect(page.getByTestId('schedule-save')).toBeDisabled()
  await page.reload()
  await expect(page.getByTestId('schedule-row')).toHaveCount(1)
  await expect(page.getByTestId('schedule-time')).toHaveValue('07:15')
  await page.getByTestId('agent-picker-toggle').click()
  await expect(page.getByTestId('agent-item').filter({ hasText: 'Horario' }).getByTestId('agent-next')).not.toBeEmpty()
})

test('guarda um segredo sem mostrar o valor em lugar nenhum', async ({ page }) => {
  const secret = 'valor-super-secreto-9f3a'
  await createAgent(page, uniqueName('Segredo'))
  await page.getByTestId('secret-new-name').fill('TOKEN_DEMO')
  await page.getByTestId('secret-new-value').fill(secret)
  await page.getByTestId('secret-add').click()
  await expect(page.getByTestId('secret-name')).toHaveText('TOKEN_DEMO')
  await expect(page.getByTestId('secret-new-value')).toHaveValue('')
  await expect(page.getByTestId('secret-new-name')).toHaveValue('')

  const check = async () => {
    expect(await page.content()).not.toContain(secret)
    await expect(page.locator('body')).not.toContainText(secret)
    const values = await page.locator('input, textarea').evaluateAll((els) => els.map((e) => (e as HTMLInputElement).value))
    expect(values).not.toContain(secret)
  }
  await check()
  await page.reload()
  await expect(page.getByTestId('secret-name')).toHaveText('TOKEN_DEMO')
  await check()
  const id = /\/agentes\/(\d+)/.exec(page.url())![1]
  const response = await page.request.get(`/api/specialists/${id}/secrets`, { headers: { 'X-Maestro': '1' } })
  expect(await response.text()).not.toContain(secret)
})

test('Rodar agora abre a conversa do agente com o selo', async ({ page, baseURL }) => {
  const name = uniqueName('Executor')
  await createAgent(page, name)
  await page.getByTestId('run-now').click()
  await page.getByRole('dialog').getByRole('button', { name: 'Rodar' }).click()
  await expect(page).toHaveURL(/\/sessions\/[0-9a-f-]+/)
  await expect(page.getByTestId('agent-badge').filter({ hasText: name }).first()).toHaveText(`Agente · ${name}`)

  // The run leaves a conversation in the shared database: stop and finish it so other specs do not see it.
  const id = /\/sessions\/([0-9a-f-]+)/.exec(page.url())![1]
  const headers = { 'X-Maestro': '1', Origin: baseURL! }
  await page.request.post(`/api/sessions/${id}/interrupt`, { headers })
  await page.request.patch(`/api/sessions/${id}`, { headers, data: { finished: true } })
  // Wait for the session to settle, so its late events do not reach the next spec's page.
  await expect
    .poll(async () => ((await (await page.request.get(`/api/sessions/${id}`, { headers })).json()) as { display_state: string }).display_state)
    .toBe('finished')
})

test('o aviso semeado aparece na Inbox com o nome do agente e some ao marcar como lido', async ({ page }) => {
  await page.goto('/inbox')
  const notices = page.getByTestId('agent-notice')
  await expect(notices).toHaveCount(1)
  const alert = notices.filter({ hasText: ALERT_TEXT })
  await expect(alert.getByTestId('agent-notice-name')).toHaveText('Triagem')
  await expect(page.getByText(SUMMARY_TEXT)).toHaveCount(0)
  const count = page.getByTestId('agents-count')
  await expect(count).toContainText('1')

  await alert.getByTestId('agent-notice-read').click()
  await expect(page.getByTestId('agent-notices')).toHaveCount(0)
  await expect(count).toHaveCount(0)
  await page.reload()
  await expect(page.getByTestId('agent-notices')).toHaveCount(0)
  await expect(page.getByTestId('nav-agents')).toBeVisible()
  await expect(page.getByTestId('agents-count')).toHaveCount(0)
})

for (const width of [1280, 800]) {
  test(`a página de agentes cabe e os controles ficam alcançáveis em ${width} px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 })
    await page.goto('/agentes')
    await page.getByTestId('agent-picker-toggle').click()
    await page.getByTestId('agent-item').filter({ hasText: 'Triagem' }).click()
    await expect(page.getByTestId('agent-name')).toHaveText('Triagem')
    await page.getByTestId('agent-tab-runs').click()
    await expect(page.getByTestId('run-row').first()).toBeVisible()
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
    expect(overflow).toBeLessThanOrEqual(0)
    const region = page.getByRole('region', { name: 'Detalhe do agente' })
    expect(await region.evaluate((el) => el.scrollWidth - el.clientWidth)).toBeLessThanOrEqual(0)
    await page.getByTestId('agent-tab-settings').click()
    for (const id of ['run-now', 'agent-menu', 'secret-new-name', 'secret-new-value']) {
      await page.getByTestId(id).scrollIntoViewIfNeeded()
      await expect(page.getByTestId(id)).toBeInViewport({ ratio: 1 })
    }
    await page.getByTestId('day').first().scrollIntoViewIfNeeded()
    await expect(page.getByTestId('day').first()).toBeInViewport({ ratio: 1 })
    await expect(page.getByTestId('day').last()).toBeInViewport({ ratio: 1 })
    await page.getByTestId('agent-menu').scrollIntoViewIfNeeded()
    await page.getByTestId('agent-menu').click()
    await expect(page.getByTestId('agent-delete')).toBeInViewport({ ratio: 1 })
    await page.keyboard.press('Escape')
    await page.getByTestId('run-now').scrollIntoViewIfNeeded()
    await page.getByTestId('run-now').click()
    await expect(page.getByRole('dialog').getByRole('button', { name: 'Rodar' })).toBeVisible()
    await page.keyboard.press('Escape')
  })

  test(`a lista continua usável em ${width} px: trocar de agente`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 })
    const name = uniqueName('Outro')
    await createAgent(page, name)
    await page.getByTestId('agent-picker-toggle').click()
    await page.getByTestId('agent-item').filter({ hasText: 'Triagem' }).click()
    await expect(page.getByTestId('agent-name')).toHaveText('Triagem')
    await page.getByTestId('agent-picker-toggle').click()
    await page.getByTestId('agent-item').filter({ hasText: name }).click()
    await expect(page.getByTestId('agent-name')).toHaveText(name)
  })
}
