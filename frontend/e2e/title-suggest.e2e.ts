import type { Page } from '@playwright/test'
import { expect, test } from './fixtures'

// The texts below are the SCENARIO of scripts/e2e_server.py. The E2E server refuses the digest
// model, so the suggestions come from a stubbed `title-suggestions` route. Renaming changes the
// shared database, so each test puts the original title back (afterEach).
const TITLE = 'Liste as tarefas pendentes'
const SUGGESTIONS = ['Tarefas pendentes do projeto', 'Checagem da lista de tarefas', 'Nada a fazer por ora']
const OTHERS = ['Pendências em dia', 'Lista de tarefas vazia', 'Balanço das tarefas']
const ROUTE = '**/api/sessions/*/title-suggestions'

test.afterEach(async ({ page, baseURL }) => {
  const headers = { 'X-Maestro': '1', Origin: baseURL! }
  const list = await page.request.get('/api/sessions', { headers })
  const sessions = (await list.json()) as { session_id: string; title: string }[]
  for (const session of sessions) {
    if (SUGGESTIONS.includes(session.title) || OTHERS.includes(session.title)) {
      await page.request.patch(`/api/sessions/${session.session_id}`, { headers, data: { title: TITLE } })
    }
  }
})

async function stubSuggestions(page: Page, rounds: string[][]) {
  let call = 0
  await page.route(ROUTE, (route) => {
    const suggestions = rounds[Math.min(call++, rounds.length - 1)]
    return route.fulfill({ json: { suggestions } })
  })
}

const sidebar = (page: Page) => page.getByRole('navigation', { name: 'Navegação' })

// Opens the conversation by URL, so a narrow window (where the list page is cramped) works too.
async function openConversation(page: Page) {
  const response = await page.request.get('/api/sessions', { headers: { 'X-Maestro': '1' } })
  const sessions = (await response.json()) as { session_id: string; title: string }[]
  await page.goto(`/sessions/${sessions.find((s) => s.title === TITLE)!.session_id}`)
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(TITLE)
}

test('escolher uma sugestão renomeia a conversa no cabeçalho e na lista lateral', async ({ page }) => {
  await stubSuggestions(page, [SUGGESTIONS])
  await openConversation(page)

  await page.getByTestId('suggest-title').click()
  const items = page.getByTestId('title-suggestion')
  await expect(items).toHaveText(SUGGESTIONS)

  await items.nth(1).click()

  await expect(page.getByTestId('title-suggest-panel')).toBeHidden()
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(SUGGESTIONS[1])
  await expect(sidebar(page).getByRole('link', { name: SUGGESTIONS[1] })).toBeVisible()
  await expect(sidebar(page).getByRole('link', { name: TITLE })).toHaveCount(0)
})

test('"Gerar outras" troca as sugestões sem renomear', async ({ page }) => {
  await stubSuggestions(page, [SUGGESTIONS, OTHERS])
  await openConversation(page)

  await page.getByTestId('suggest-title').click()
  await expect(page.getByTestId('title-suggestion')).toHaveText(SUGGESTIONS)

  await page.getByTestId('suggest-again').click()

  await expect(page.getByTestId('title-suggestion')).toHaveText(OTHERS)
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(TITLE)
})

test('Esc e clique fora fecham o painel sem renomear', async ({ page }) => {
  await stubSuggestions(page, [SUGGESTIONS])
  await openConversation(page)
  const panel = page.getByTestId('title-suggest-panel')

  await page.getByTestId('suggest-title').click()
  await expect(page.getByTestId('title-suggestion')).toHaveCount(3)
  await page.keyboard.press('Escape')
  await expect(panel).toBeHidden()
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(TITLE)
  // The Esc must not trigger anything else of the header (edit mode, navigation).
  await expect(page).toHaveURL(/\/sessions\/[0-9a-f-]+$/)
  await expect(page.getByRole('textbox', { name: /título/i })).toHaveCount(0)
  // The details panel stays open: that Esc was consumed by the suggestion panel.
  await expect(page.getByTestId('prop-labels')).toBeVisible()

  await page.getByTestId('suggest-title').click()
  await expect(page.getByTestId('title-suggestion')).toHaveCount(3)
  // Empty spot of the thread, below the panel.
  await page.mouse.click(600, 450)
  await expect(panel).toBeHidden()
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(TITLE)
})

test('o erro aparece no painel e o título fica intacto', async ({ page, consoleErrors }) => {
  await page.route(ROUTE, (route) =>
    route.fulfill({ status: 502, json: { detail: 'O modelo não respondeu.' } }),
  )
  await openConversation(page)

  await page.getByTestId('suggest-title').click()

  await expect(page.getByTestId('title-suggest-error')).toHaveText('O modelo não respondeu.')
  await expect(page.getByTestId('title-suggestion')).toHaveCount(0)
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(TITLE)
  // Chrome logs the 502 itself as a console error; that is the expected one here.
  expect(consoleErrors.some((text) => text.includes('502'))).toBe(true)
  consoleErrors.length = 0
})

test('o botão some na edição manual e clicar no título continua editando', async ({ page }) => {
  await openConversation(page)
  await expect(page.getByTestId('suggest-title')).toHaveAccessibleName('Sugerir título')

  await page.getByRole('heading', { level: 1 }).getByRole('button').click()

  await expect(page.getByTestId('suggest-title')).toHaveCount(0)
})

for (const width of [400, 1280]) {
  test(`o painel cabe na janela de ${width}px, sem rolagem horizontal`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 })
    await stubSuggestions(page, [SUGGESTIONS])
    await openConversation(page)

    await page.getByTestId('suggest-title').click()
    await expect(page.getByTestId('title-suggestion')).toHaveCount(3)

    const box = await page.getByTestId('title-suggest-panel').boundingBox()
    expect(box!.x).toBeGreaterThanOrEqual(0)
    expect(box!.x + box!.width).toBeLessThanOrEqual(width)
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    )
    expect(overflow).toBeLessThanOrEqual(0)
  })
}
