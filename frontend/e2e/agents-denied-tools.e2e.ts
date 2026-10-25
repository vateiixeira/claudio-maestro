import type { Page } from '@playwright/test'
import { expect, test } from './fixtures'

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

test('bloqueia ferramentas: acrescenta, persiste ao recarregar e remove', async ({ page }) => {
  await createAgent(page, uniqueName('Bloqueio'))
  const input = page.getByTestId('denied-input')
  const chips = page.getByTestId('denied-custom')
  await expect(page.getByRole('heading', { name: 'Ferramentas bloqueadas' })).toBeVisible()

  await input.fill('mcp__kbgen-issues__editar_issue')
  await page.getByTestId('denied-add').click()
  await expect(chips).toHaveCount(1)
  await expect(input).toHaveValue('')
  await input.fill('mcp__kbgen-issues')
  await input.press('Enter')
  await expect(chips).toHaveCount(2)

  await page.reload()
  await expect(chips).toHaveCount(2)
  await expect(chips.nth(0)).toContainText('mcp__kbgen-issues__editar_issue')
  await expect(chips.nth(1)).toContainText('mcp__kbgen-issues')

  await page.getByRole('button', { name: 'Remover mcp__kbgen-issues__editar_issue' }).click()
  await expect(chips).toHaveCount(1)
  await page.reload()
  await expect(chips).toHaveCount(1)
  await expect(chips.first()).toHaveText(/^\s*mcp__kbgen-issues\s*$/)
})

test('nome inválido mostra o erro em pt-BR, mantém o texto e não afeta os outros campos', async ({ page, consoleErrors }) => {
  await createAgent(page, uniqueName('Invalido'))
  const input = page.getByTestId('denied-input')
  const error = page.getByTestId('action-error')

  for (const bad of ['Bash(rm:*)', 'mcp__x__*']) {
    await input.fill(bad)
    await page.getByTestId('denied-add').click()
    await expect(error).toBeVisible()
    await expect(error).toContainText('Sem parênteses, espaços nem curingas.')
    await expect(input).toHaveValue(bad)
    await expect(page.getByTestId('denied-custom')).toHaveCount(0)
  }
  // The browser logs each refused request (422) by itself: expected here.
  consoleErrors.splice(0, consoleErrors.length, ...consoleErrors.filter((m) => !m.includes('status of 422')))

  // A valid value afterwards saves and clears the banner.
  await input.fill('WebFetch')
  await page.getByTestId('denied-add').click()
  await expect(page.getByTestId('denied-custom')).toHaveCount(1)
  await expect(error).toHaveCount(0)
})

test('os campos vizinhos de padrões continuam independentes do de ferramentas', async ({ page }) => {
  await createAgent(page, uniqueName('Vizinhos'))
  await page.getByTestId('outward-input').fill('npm publish --tag x')
  await page.getByTestId('outward-add').click()
  await page.getByTestId('always-input').fill('docker push x')
  await page.getByTestId('always-add').click()
  await page.getByTestId('denied-input').fill('WebFetch')
  await page.getByTestId('denied-add').click()
  await expect(page.getByTestId('denied-custom')).toHaveCount(1)
  await page.reload()
  await expect(page.getByTestId('outward-custom')).toHaveText(/npm publish --tag x/)
  await expect(page.getByTestId('always-custom')).toHaveText(/docker push x/)
  await expect(page.getByTestId('denied-custom')).toHaveText(/WebFetch/)
  await page.getByTestId('outward-custom').getByTestId('pattern-remove').click()
  await expect(page.getByTestId('outward-custom')).toHaveCount(0)
  await expect(page.getByTestId('denied-custom')).toHaveCount(1)
})

for (const width of [1280, 600]) {
  test(`o campo de ferramentas bloqueadas cabe em ${width} px e não cita a marca antiga`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 })
    await createAgent(page, uniqueName('Largura'))
    await page.getByTestId('denied-input').scrollIntoViewIfNeeded()
    await expect(page.getByTestId('denied-input')).toBeInViewport({ ratio: 1 })
    await expect(page.getByTestId('denied-add')).toBeInViewport({ ratio: 1 })
    expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0)
    await expect(page.getByText('Vale por completo nas sessões abertas depois de salvar.')).toBeVisible()
    await expect(page.locator('body')).not.toContainText('Claude Code')
  })
}
