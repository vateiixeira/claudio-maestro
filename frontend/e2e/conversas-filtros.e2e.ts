import type { Page } from '@playwright/test'
import { expect, test } from './fixtures'

// The seeded conversations are all closed, read and "Sua vez", so every chip would show the same list. The lists of
// each project that reach the page are patched on the way in (nothing is written to the server) so the chips differ:
// one conversation runs, one has news, one is finished and one is marked "Para revisar".
const RUNNING = 'Liste as tarefas pendentes'
const UNREAD = 'Resuma o último commit'
const FINISHED = 'Conversa com imagens'
const REVIEW = 'Como configuro a jornada do funil?'
const PLAIN = 'Investigue o módulo de pagamentos'

async function patchSessions(page: Page) {
  await page.route(/\/api\/projects\/\d+\/sessions(\?.*)?$/, async (route) => {
    const response = await route.fetch()
    const sessions = (await response.json()) as Record<string, unknown>[]
    for (const session of sessions) {
      if (session.title === RUNNING) Object.assign(session, { display_state: 'running', state: 'running' })
      if (session.title === UNREAD) Object.assign(session, { display_state: 'waiting', unread: true })
      if (session.title === FINISHED) Object.assign(session, { display_state: 'finished', finished: true, finished_at: session.last_activity_at })
      if (session.title === REVIEW) Object.assign(session, { mark: 'review' })
    }
    await route.fulfill({ response, json: sessions })
  })
}

const chip = (page: Page, state: string) => page.locator(`[data-test="conversations-chip"][data-state="${state}"]`)
const rows = (page: Page) => page.getByTestId('conversation-row')
const row = (page: Page, title: string) => rows(page).filter({ hasText: title })
const estado = (page: Page) => new URL(page.url()).searchParams.get('estado')

test('cada chip muda o ?estado= e a lista de conversas', async ({ page }) => {
  await patchSessions(page)
  await page.goto('/sessions')
  await expect(chip(page, 'todas')).toHaveAttribute('aria-pressed', 'true')
  await expect(rows(page)).toHaveCount(8)
  expect(estado(page)).toBeNull()

  await chip(page, 'em-execucao').click()
  await expect(page).toHaveURL(/estado=em-execucao/)
  await expect(chip(page, 'em-execucao')).toHaveAttribute('aria-pressed', 'true')
  await expect(chip(page, 'todas')).toHaveAttribute('aria-pressed', 'false')
  await expect(rows(page)).toHaveCount(1)
  await expect(row(page, RUNNING)).toBeVisible()
  await expect(chip(page, 'em-execucao').getByTestId('filter-chip-count')).toHaveText('1')

  await chip(page, 'nao-lidas').click()
  await expect(page).toHaveURL(/estado=nao-lidas/)
  await expect(rows(page)).toHaveCount(1)
  await expect(row(page, UNREAD)).toBeVisible()

  await chip(page, 'finalizadas').click()
  await expect(page).toHaveURL(/estado=finalizadas/)
  await expect(rows(page)).toHaveCount(1)
  await expect(row(page, FINISHED)).toBeVisible()

  // "Sua vez" keeps what waits for you now: not the running one, the finished one nor the one marked for review.
  await chip(page, 'sua-vez').click()
  await expect(page).toHaveURL(/estado=sua-vez/)
  await expect(row(page, PLAIN)).toBeVisible()
  await expect(row(page, RUNNING)).toHaveCount(0)
  await expect(row(page, FINISHED)).toHaveCount(0)
  await expect(row(page, REVIEW)).toHaveCount(0)
  const waiting = Number(await chip(page, 'sua-vez').getByTestId('filter-chip-count').innerText())
  await expect(rows(page)).toHaveCount(waiting)

  // "Todas" takes the state out of the address and brings everything back.
  await chip(page, 'todas').click()
  await expect(rows(page)).toHaveCount(8)
  await expect.poll(() => estado(page)).toBeNull()
})

test('"Mais filtros" leva a "Para revisar" e a opção vazia tira o estado', async ({ page }) => {
  await patchSessions(page)
  await page.goto('/sessions')
  const more = page.getByTestId('conversations-state')
  await expect(more).toHaveValue('')

  await more.selectOption('para-revisar')
  await expect(page).toHaveURL(/estado=para-revisar/)
  await expect(rows(page)).toHaveCount(1)
  await expect(row(page, REVIEW)).toBeVisible()
  // None of the chips is the one in use, and the select shows the choice.
  for (const state of ['todas', 'em-execucao', 'sua-vez', 'nao-lidas', 'finalizadas']) {
    await expect(chip(page, state)).toHaveAttribute('aria-pressed', 'false')
  }
  await expect(more).toHaveValue('para-revisar')

  // Going back to a chip empties the select.
  await chip(page, 'em-execucao').click()
  await expect(more).toHaveValue('')

  await more.selectOption('para-revisar')
  await expect(rows(page)).toHaveCount(1)
  await more.selectOption('')
  await expect.poll(() => estado(page)).toBeNull()
  await expect(rows(page)).toHaveCount(8)
})

test('abrir a tela já num estado do endereço marca o chip e filtra a lista', async ({ page }) => {
  await patchSessions(page)
  await page.goto('/sessions?estado=nao-lidas')
  await expect(chip(page, 'nao-lidas')).toHaveAttribute('aria-pressed', 'true')
  await expect(rows(page)).toHaveCount(1)
  await expect(row(page, UNREAD)).toBeVisible()
})
