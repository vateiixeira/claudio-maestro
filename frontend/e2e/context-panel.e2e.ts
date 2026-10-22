import type { Page } from '@playwright/test'
import { expect, test } from './fixtures'

// The seeded conversations have no context reading and the seeded server opens no agent, so the
// context is staged: the snapshot of a conversation carries `context`, and the breakdown route is
// either the real one (answers `no_process`) or answered by the spec.

const CONTEXT = { used_tokens: 84800, max_tokens: 400000, percent: 21.2 }

type Category = { name: string; tokens: number; kind: 'used' | 'buffer' | 'free' | 'deferred' }
const categories: Category[] = [
  { name: 'Messages', tokens: 35760, kind: 'used' },
  { name: 'System tools', tokens: 15900, kind: 'used' },
  { name: 'MCP tools', tokens: 11600, kind: 'used' },
  { name: 'Skills', tokens: 10000, kind: 'used' },
  { name: 'System prompt', tokens: 7700, kind: 'used' },
  { name: 'Memory files', tokens: 2100, kind: 'used' },
  { name: 'Custom agents', tokens: 1300, kind: 'used' },
  { name: 'MCP server instructions', tokens: 787, kind: 'used' },
  { name: 'Autocompact buffer', tokens: 33000, kind: 'buffer' },
  { name: 'Free space', tokens: 281900, kind: 'free' },
  { name: 'MCP tools (deferred)', tokens: 80300, kind: 'deferred' },
  { name: 'System tools (deferred)', tokens: 23800, kind: 'deferred' },
]
const BREAKDOWN = {
  available: true,
  context: CONTEXT,
  breakdown: {
    model: 'claude-opus-5-5',
    total_tokens: 84800,
    max_tokens: 400000,
    percent: 21.2,
    categories,
    mcp_tools: [
      { name: 'smart_search', server: 'claude-mem', tokens: 1900, loaded: true },
      { name: 'timeline', server: 'claude-mem', tokens: 1200, loaded: true },
      { name: 'build_corpus', server: 'claude-mem', tokens: 900, loaded: false },
      { name: 'list_events', server: 'calendar', tokens: 700, loaded: false },
    ],
    memory_files: [{ path: '/home/demo/.claude/CLAUDE.md', tokens: 900 }],
    agents: [{ name: 'implementer', tokens: 200 }],
    skills: [{ name: 'superpowers:brainstorming', tokens: 400 }],
  },
}

async function stageContext(page: Page, route?: { json: unknown }) {
  await page.route(/\/api\/sessions\/[0-9a-f-]+$/, async (r) => {
    if (r.request().method() !== 'GET') return r.fallback()
    const response = await r.fetch()
    const snapshot = await response.json()
    await r.fulfill({ response, json: { ...snapshot, context: CONTEXT } })
  })
  if (route) {
    await page.route(/\/api\/sessions\/[0-9a-f-]+\/context$/, (r) => r.fulfill({ json: route.json }))
  }
}

async function openConversation(page: Page) {
  await page.goto('/sessions')
  await page.getByText('Explique a estrutura do projeto').first().click()
  await expect(page).toHaveURL(/\/sessions\/[0-9a-f-]+/)
}

const indicator = (page: Page) => page.getByTestId('context-usage')
const popover = (page: Page) => page.getByTestId('context-popover')

test('numa sessão fechada o indicador abre o total e a frase de sessão fechada', async ({ page }) => {
  await stageContext(page)
  await openConversation(page)

  await expect(indicator(page)).toBeVisible()
  await expect(indicator(page)).toContainText('21%')
  await indicator(page).click()

  await expect(popover(page)).toBeVisible()
  await expect(popover(page).getByTestId('ctx-percent')).toHaveText('21% usado')
  await expect(popover(page).getByTestId('ctx-tokens')).toContainText('84,8 mil')
  await expect(popover(page).getByTestId('ctx-message')).toHaveText('O detalhamento aparece quando a sessão estiver aberta.')
})

test('o detalhamento mostra cabeçalho, barra, espaço livre, deferred e as sublistas', async ({ page }) => {
  await stageContext(page, { json: BREAKDOWN })
  await openConversation(page)
  await indicator(page).click()

  const pop = popover(page)
  await expect(pop.getByTestId('ctx-percent')).toHaveText('21% usado')
  await expect(pop.getByTestId('ctx-tokens')).toContainText('84,8 mil')
  await expect(pop.getByTestId('ctx-tokens')).toContainText('400')

  // 4 colored series + "Outros" + the autocompact buffer.
  await expect(pop.getByTestId('ctx-segment')).toHaveCount(6)
  await expect(pop.locator('[data-test=ctx-segment][title^="Outros"]')).toHaveCount(1)
  await expect(pop.locator('[data-test=ctx-segment][title^="Autocompact buffer"]')).toHaveCount(1)

  const row = (name: string) => pop.getByTestId('ctx-row').filter({ hasText: name })
  await expect(row('Espaço livre')).toBeVisible()
  await expect(row('Espaço livre')).toContainText('281,9 mil')
  await expect(row('System tools (deferred)')).toContainText('—')
  await expect(row('MCP tools (deferred)')).toContainText('—')

  // Loaded tools hang under "MCP tools"; the others under the deferred row.
  const mcp = pop.getByRole('button', { name: /^MCP tools\b(?!.*deferred)/ })
  await expect(mcp).toHaveAttribute('aria-expanded', 'false')
  await mcp.click()
  await expect(mcp).toHaveAttribute('aria-expanded', 'true')
  const loaded = pop.getByTestId('ctx-details')
  await expect(loaded).toHaveCount(1)
  await expect(loaded).toContainText('claude-mem · smart_search')
  await expect(loaded).toContainText('claude-mem · timeline')
  await expect(loaded).not.toContainText('build_corpus')
  await mcp.click()
  await expect(pop.getByTestId('ctx-details')).toHaveCount(0)

  const deferred = pop.getByRole('button', { name: /MCP tools \(deferred\)/ })
  await deferred.click()
  const notLoaded = pop.getByTestId('ctx-details')
  await expect(notLoaded).toContainText('claude-mem · build_corpus')
  await expect(notLoaded).toContainText('calendar · list_events')
  await expect(notLoaded).not.toContainText('smart_search')
  await deferred.click()
  await expect(pop.getByTestId('ctx-details')).toHaveCount(0)
})

test('a seção Contexto do painel de detalhes mostra o mesmo detalhamento', async ({ page }) => {
  await stageContext(page, { json: BREAKDOWN })
  await openConversation(page)
  await page.getByTestId('details-tab-details').click()

  const section = page.getByTestId('prop-context')
  await expect(section.getByTestId('ctx-percent')).toHaveText('21% usado')
  await expect(section.getByTestId('ctx-tokens')).toContainText('84,8 mil')
  await expect(section.getByTestId('ctx-segment')).toHaveCount(6)
  await expect(section.getByTestId('ctx-row').filter({ hasText: 'Espaço livre' })).toBeVisible()
  await expect(section.getByTestId('ctx-row').filter({ hasText: 'System tools (deferred)' })).toContainText('—')

  const mcp = section.getByRole('button', { name: /^MCP tools\b(?!.*deferred)/ })
  await mcp.click()
  await expect(section.getByTestId('ctx-details')).toContainText('claude-mem · smart_search')
  await expect(section.getByTestId('ctx-details')).not.toContainText('build_corpus')
  await mcp.click()
  await expect(section.getByTestId('ctx-details')).toHaveCount(0)
})

test('Esc fecha o popover e devolve o foco ao indicador; o clique fora também fecha', async ({ page }) => {
  await stageContext(page, { json: BREAKDOWN })
  await openConversation(page)

  await indicator(page).click()
  await expect(popover(page)).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(popover(page)).toHaveCount(0)
  await expect(indicator(page)).toBeFocused()

  await indicator(page).click()
  await expect(popover(page)).toBeVisible()
  await page.mouse.click(5, 5)
  await expect(popover(page)).toHaveCount(0)
})

test('quando o cálculo falha o popover mostra a frase de erro', async ({ page }) => {
  await stageContext(page, { json: { available: false, reason: 'failed', context: CONTEXT } })
  await openConversation(page)
  await indicator(page).click()

  await expect(popover(page).getByTestId('ctx-message')).toHaveText('Não foi possível calcular o detalhamento agora.')
  await expect(popover(page).getByTestId('ctx-percent')).toHaveText('21% usado')
})

test('na seção Contexto do painel os rótulos e o cabeçalho cabem sem ser cortados', async ({ page }) => {
  await stageContext(page, { json: BREAKDOWN })
  await openConversation(page)
  await page.getByTestId('details-tab-details').click()

  const section = page.getByTestId('prop-context')
  await expect(section.getByTestId('ctx-row')).not.toHaveCount(0)
  const labels = ['Messages', 'System tools', 'MCP tools', 'Skills', 'Autocompact buffer', 'Espaço livre']
  for (const name of labels) {
    const label = section.getByTestId('ctx-row').getByText(name, { exact: true })
    const clipped = await label.evaluate((el) => el.scrollWidth > el.clientWidth)
    expect(clipped, `o rótulo "${name}" está cortado`).toBe(false)
  }
  // The header stays on one line: "21% usado" is as tall as one line of text.
  const percent = section.getByTestId('ctx-percent')
  const lineHeight = await percent.evaluate((el) => parseFloat(getComputedStyle(el).lineHeight) || el.clientHeight)
  expect((await percent.boundingBox())!.height).toBeLessThanOrEqual(lineHeight + 2)
})
