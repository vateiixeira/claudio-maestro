import type { Page } from '@playwright/test'
import { expect, test } from './fixtures'

// The seeded scenario has one agent with notices, a single unread one with one line of text. To have several agents,
// a long text and more than one unread notice, the answer of /api/agent-notices is replaced (made-up notices) and the
// "mark as read" call is answered by the test, so nothing is written to the seeded database and other specs keep
// the notice they count on.
const LONG_BODY = 'Primeiro parágrafo do relatório de revisão.\n\nSegundo parágrafo com o detalhe que só aparece lido por inteiro.'

interface Seed { alert: number; review: number; plan: number; old: number; triagem: number; revisor: number; maestro: number }

async function seedNotices(page: Page): Promise<{ ids: Seed; reads: number[][] }> {
  const response = await page.request.get('/api/agents', { headers: { 'X-Maestro': '1' } })
  const agents = (await response.json()) as { id: number; name: string }[]
  const byName = (name: string) => agents.find((a) => a.name === name)!.id
  const triagem = byName('Triagem')
  const revisor = byName('Revisor')
  const maestro = byName('Maestro')
  const now = Math.floor(Date.now() / 1000)
  const notices = [
    { id: 9101, agent_id: triagem, run_id: null, kind: 'alert', text: 'Triagem travou nos chamados urgentes.', created_at: now - 3600, read_at: null },
    { id: 9102, agent_id: revisor, run_id: null, kind: 'summary', text: `**Revisão concluída**\n${LONG_BODY}`, created_at: now - 1800, read_at: null },
    { id: 9103, agent_id: maestro, run_id: null, kind: 'summary', text: 'Plano da semana pronto', created_at: now - 900, read_at: null },
    { id: 9104, agent_id: triagem, run_id: null, kind: 'summary', text: 'Triagem de ontem concluída', created_at: now - 30 * 3600, read_at: now - 29 * 3600 },
  ]
  const reads: number[][] = []
  await page.route('**/api/agent-notices', (route) => route.fulfill({ json: notices }))
  await page.route('**/api/agent-notices/read', async (route) => {
    const ids = (route.request().postDataJSON() as { ids: number[] }).ids
    reads.push(ids)
    await route.fulfill({ json: { updated: ids.length } })
  })
  return { ids: { alert: 9101, review: 9102, plan: 9103, old: 9104, triagem, revisor, maestro }, reads }
}

const notice = (page: Page, id: number) => page.locator(`[data-test="agent-notice"][data-notice-id="${id}"]`)
const chip = (page: Page, filter: string) => page.locator(`[data-test="notice-filter"][data-filter="${filter}"]`)

test('a Inbox abre em Novidades, com o que os agentes deixaram, do mais novo ao mais antigo', async ({ page }) => {
  const { ids } = await seedNotices(page)
  await page.goto('/inbox')
  await expect(page.getByRole('heading', { name: 'Inbox', level: 1 })).toBeVisible()
  await expect(page.getByTestId('inbox-view-novidades')).toHaveAttribute('aria-current', 'page')
  await expect(page.getByTestId('inbox-view-conversas')).not.toHaveAttribute('aria-current', 'page')
  await expect(page.getByTestId('inbox-unread')).toHaveText('3 novidades')
  await expect(page.getByTestId('notice-feed')).toBeVisible()
  await expect(page.getByTestId('agent-notice')).toHaveCount(4)
  // Newest first.
  await expect(page.getByTestId('agent-notice')).toHaveText([/Plano da semana pronto/, /Revisão concluída/, /Triagem travou/, /Triagem de ontem/])
  // The unread ones are marked, the read one is not.
  await expect(notice(page, ids.plan)).toHaveAttribute('data-unread', 'true')
  await expect(notice(page, ids.old)).toHaveAttribute('data-unread', 'false')
  // Without a body there is no "read all here".
  await notice(page, ids.plan).getByTestId('agent-notice-select').click()
  await expect(notice(page, ids.plan).getByTestId('notice-read-full')).toHaveCount(0)
  await notice(page, ids.review).getByTestId('agent-notice-select').click()
  await expect(notice(page, ids.review).getByTestId('notice-read-full')).toBeVisible()
})

test('o chip de um agente filtra as novidades e tocar de novo volta a todas', async ({ page }) => {
  const { ids } = await seedNotices(page)
  await page.goto('/inbox?aba=novidades')
  await expect(page.getByTestId('agent-notice')).toHaveCount(4)
  await expect(chip(page, 'all')).toHaveAttribute('aria-pressed', 'true')

  await chip(page, `agent-${ids.triagem}`).click()
  await expect(chip(page, `agent-${ids.triagem}`)).toHaveAttribute('aria-pressed', 'true')
  await expect(chip(page, 'all')).toHaveAttribute('aria-pressed', 'false')
  await expect(page.getByTestId('agent-notice')).toHaveCount(2)
  await expect(page.getByTestId('agent-notice-name')).toHaveText(['Triagem', 'Triagem'])

  await chip(page, `agent-${ids.revisor}`).click()
  await expect(page.getByTestId('agent-notice')).toHaveCount(1)
  await expect(notice(page, ids.review)).toBeVisible()

  // The chip of "Pedem atenção" keeps only the alerts.
  await chip(page, 'alert').click()
  await expect(page.getByTestId('agent-notice')).toHaveCount(1)
  await expect(notice(page, ids.alert)).toBeVisible()

  await chip(page, 'alert').click()
  await expect(chip(page, 'all')).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByTestId('agent-notice')).toHaveCount(4)
})

test('j e k selecionam, Enter mostra o texto inteiro e e marca como lida', async ({ page }) => {
  const { ids, reads } = await seedNotices(page)
  await page.goto('/inbox?aba=novidades')
  await expect(page.getByTestId('agent-notice')).toHaveCount(4)
  await expect(page.locator('[data-test="agent-notice"][data-selected="true"]')).toHaveCount(0)

  await page.keyboard.press('j')
  await expect(notice(page, ids.plan)).toHaveAttribute('data-selected', 'true')
  await page.keyboard.press('j')
  await expect(notice(page, ids.review)).toHaveAttribute('data-selected', 'true')
  await expect(notice(page, ids.plan)).toHaveAttribute('data-selected', 'false')
  await page.keyboard.press('k')
  await expect(notice(page, ids.plan)).toHaveAttribute('data-selected', 'true')
  await page.keyboard.press('j')

  // Enter shows the whole text of the selected notice, and again folds it.
  const text = notice(page, ids.review).getByTestId('agent-notice-text')
  // Folded, the body runs on in at most two lines; unfolded, it keeps its paragraphs.
  await expect(text).toHaveCSS('white-space', 'normal')
  await page.keyboard.press('Enter')
  await expect(text).toHaveCSS('white-space', 'pre-line')
  await expect(text).toContainText('Segundo parágrafo com o detalhe que só aparece lido por inteiro.')
  await expect(notice(page, ids.review).getByTestId('notice-read-full')).toHaveAttribute('aria-expanded', 'true')
  await page.keyboard.press('Enter')
  await expect(text).toHaveCSS('white-space', 'normal')

  // "e" marks the selected one as read: it stays in the list, no longer unread, and the counters follow.
  await expect(page.getByTestId('inbox-unread')).toHaveText('3 novidades')
  await page.keyboard.press('e')
  await expect(notice(page, ids.review)).toHaveAttribute('data-unread', 'false')
  await expect(notice(page, ids.review)).toBeVisible()
  await expect(page.getByTestId('inbox-unread')).toHaveText('2 novidades')
  expect(reads).toEqual([[ids.review]])
  // On a read notice "e" does nothing.
  await page.keyboard.press('e')
  expect(reads).toEqual([[ids.review]])
})

test('Conversas, na Inbox, leva à lista de conversas e Novidades volta', async ({ page }) => {
  await seedNotices(page)
  await page.goto('/inbox')
  await page.getByTestId('inbox-view-conversas').click()
  await expect(page).toHaveURL(/\/inbox\?aba=pede-voce$/)
  await expect(page.getByTestId('inbox-view-conversas')).toHaveAttribute('aria-current', 'page')
  await expect(page.getByTestId('notice-feed')).toHaveCount(0)
  await expect(page.getByRole('tablist', { name: 'Filtro da Inbox' })).toBeVisible()

  await page.getByTestId('inbox-view-novidades').click()
  await expect(page).toHaveURL(/\/inbox\?aba=novidades$/)
  await expect(page.getByTestId('notice-feed')).toBeVisible()
})
