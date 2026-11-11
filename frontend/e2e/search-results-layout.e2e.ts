import { expect, test } from './fixtures'

// The list of results is capped in height; with many results that carry a snippet and labels, each item
// must keep its natural height (the list scrolls) instead of being squeezed until the title vanishes.
// Labels are global and the database lives through the whole run: the test deletes the ones it made.
test.afterEach(async ({ page, baseURL }) => {
  const headers = { 'X-Maestro': '1', Origin: baseURL! }
  const list = await page.request.get('/api/labels', { headers })
  for (const label of (await list.json()) as { id: number }[]) {
    await page.request.delete(`/api/labels/${label.id}`, { headers })
  }
})

type Page = import('@playwright/test').Page

const LONG = 'a resposta continua por bastante tempo e chega a ocupar mais de uma linha inteira do trecho da busca, '.repeat(3)

interface Options {
  count: number
  withLabel?: boolean
  withSnippet?: boolean
  // Real session ids by position, so that opening one does not hit a missing conversation.
  real?: Record<number, string>
}

// Mocks the search with `count` results and runs it. Returns the session ids of the mocked results.
async function searchWith(page: Page, baseURL: string, { count, withLabel = true, withSnippet = true, real = {} }: Options) {
  const headers = { 'X-Maestro': '1', Origin: baseURL }
  let labelId: number | null = null
  if (withLabel) {
    const made = await page.request.post('/api/labels', { headers, data: { slug: 'busca-layout', color: '#1d4ed8' } })
    expect(made.ok()).toBeTruthy()
    labelId = ((await made.json()) as { id: number }).id
  }
  const projects = (await (await page.request.get('/api/projects', { headers })).json()) as { id: number }[]
  const base = (await (await page.request.get('/api/sessions', { headers })).json()) as Record<string, unknown>[] | undefined
  const template = (Array.isArray(base) ? base[0] : undefined) ?? {}
  const results = Array.from({ length: count }, (_, index) => ({
    ...template,
    session_id: real[index] ?? `00000000-0000-4000-8000-${String(index).padStart(12, '0')}`,
    project_id: projects[0]?.id ?? 1,
    cwd: '/tmp/nao-importa',
    title: `Resultado número ${index + 1} com título`,
    created_at: 1_700_000_000,
    last_activity_at: 1_700_000_000 + index,
    state: 'idle',
    error: null,
    last_seen_at: null,
    finished: false,
    seq: 1,
    display_state: 'idle',
    unread: false,
    awaiting_decision: false,
    label_ids: labelId === null ? [] : [labelId],
    match: withSnippet
      ? { at: 1_700_000_000, parts: [{ text: 'começo ', hit: false }, { text: 'termo', hit: true }, { text: ` ${LONG}`, hit: false }] }
      : null,
  }))
  await page.route('**/api/sessions/search?*', (route) => route.fulfill({ json: results }))
  await page.goto('/sessions')
  await page.getByTestId('search-input').fill('termo')
  await expect(page.getByTestId('search-result')).toHaveCount(count)
  // The label line shows once the labels store has loaded; measuring before that catches the list mid-layout.
  if (withLabel) await expect(page.getByTestId('search-labels')).toHaveCount(count)
  return results
}

// Every item keeps its natural height and stacks title, labels, project line and snippet without overlap.
async function expectItemsIntact(page: Page, count: number, { withLabel = true, withSnippet = true } = {}) {
  const items = page.getByTestId('search-result')
  const lineHeight = withSnippet
    ? await items.first().getByTestId('search-snippet').evaluate((element) => parseFloat(getComputedStyle(element).lineHeight))
    : 0
  for (let index = 0; index < count; index++) {
    const item = items.nth(index)
    await item.scrollIntoViewIfNeeded()
    const rows = item.locator(':scope > span')
    const title = (await rows.first().boundingBox())!
    const meta = (await rows.nth(withLabel ? 2 : 1).boundingBox())!
    expect(title.height, `título do item ${index + 1} visível`).toBeGreaterThan(8)
    expect(meta.height, `linha de projeto do item ${index + 1} visível`).toBeGreaterThan(8)
    let above = title
    if (withLabel) {
      const labels = (await item.getByTestId('search-labels').boundingBox())!
      expect(labels.height, `etiquetas do item ${index + 1} visíveis`).toBeGreaterThan(8)
      expect(title.y + title.height, `título acima das etiquetas no item ${index + 1}`).toBeLessThanOrEqual(labels.y + 1)
      expect(labels.y + labels.height, `etiquetas acima da linha de projeto no item ${index + 1}`).toBeLessThanOrEqual(meta.y + 1)
      above = labels
    } else {
      expect(above.y + above.height, `título acima da linha de projeto no item ${index + 1}`).toBeLessThanOrEqual(meta.y + 1)
      await expect(item.getByTestId('search-labels')).toHaveCount(0)
    }
    if (withSnippet) {
      const snippet = (await item.getByTestId('search-snippet').boundingBox())!
      // At least one whole line of the snippet (it is clamped to two, so it never needs more than that).
      expect(snippet.height, `trecho do item ${index + 1} com ao menos uma linha`).toBeGreaterThanOrEqual(lineHeight - 1)
      expect(meta.y + meta.height, `linha de projeto acima do trecho no item ${index + 1}`).toBeLessThanOrEqual(snippet.y + 1)
      // The item contains its snippet: nothing spills out of the button.
      const box = (await item.boundingBox())!
      expect(snippet.y + snippet.height, `trecho dentro do item ${index + 1}`).toBeLessThanOrEqual(box.y + box.height + 1)
    }
  }
}

const listOf = (page: Page) => page.getByRole('list', { name: 'Resultados da busca' })

test('com muitos resultados com trecho a lista rola e cada item mantém título, etiquetas e trecho inteiros', async ({ page, baseURL }) => {
  await searchWith(page, baseURL!, { count: 12 })
  const scroll = await listOf(page).evaluate((element) => ({ scrollHeight: element.scrollHeight, clientHeight: element.clientHeight }))
  expect(scroll.scrollHeight, 'a lista passa da altura máxima e rola').toBeGreaterThan(scroll.clientHeight)
  await expectItemsIntact(page, 12)
})

for (const sidebar of [240, 480]) {
  test(`em tela baixa, num tema escuro e com a barra lateral em ${sidebar}px os itens continuam inteiros`, async ({ page, baseURL }) => {
    await page.setViewportSize({ width: 1280, height: 700 })
    await page.addInitScript((width) => {
      localStorage.setItem('maestro:sidebar-width', String(width))
      localStorage.setItem('maestro:theme', 'dracula')
    }, sidebar)
    await searchWith(page, baseURL!, { count: 12 })
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dracula')
    await expectItemsIntact(page, 12)
  })
}

test('sem etiquetas e com trecho os itens continuam inteiros e a lista rola', async ({ page, baseURL }) => {
  await searchWith(page, baseURL!, { count: 12, withLabel: false })
  await expectItemsIntact(page, 12, { withLabel: false })
})

test('com etiquetas e sem trecho os itens continuam inteiros', async ({ page, baseURL }) => {
  await searchWith(page, baseURL!, { count: 12, withSnippet: false })
  await expectItemsIntact(page, 12, { withSnippet: false })
})

test('com poucos resultados a lista não rola e nenhum item é cortado', async ({ page, baseURL }) => {
  await searchWith(page, baseURL!, { count: 2 })
  const scroll = await listOf(page).evaluate((element) => ({ scrollHeight: element.scrollHeight, clientHeight: element.clientHeight }))
  expect(scroll.scrollHeight, 'a lista cabe sem rolar').toBeLessThanOrEqual(scroll.clientHeight)
  await expectItemsIntact(page, 2)
})

async function realSessionIds(page: Page, baseURL: string): Promise<string[]> {
  const headers = { 'X-Maestro': '1', Origin: baseURL }
  const sessions = (await (await page.request.get('/api/sessions', { headers })).json()) as { session_id: string }[]
  expect(sessions.length, 'o cenário tem ao menos duas sessões').toBeGreaterThanOrEqual(2)
  return sessions.map((session) => session.session_id)
}

test('Enter abre o primeiro resultado', async ({ page, baseURL }) => {
  const ids = await realSessionIds(page, baseURL!)
  await searchWith(page, baseURL!, { count: 12, real: { 0: ids[0], 7: ids[1] } })
  await page.getByTestId('search-input').press('Enter')
  await expect(page).toHaveURL(new RegExp(`/sessions/${ids[0]}`))
})

test('Esc limpa a busca e fecha a lista de resultados', async ({ page, baseURL }) => {
  await searchWith(page, baseURL!, { count: 12 })
  await page.getByTestId('search-input').press('Escape')
  await expect(page.getByTestId('search-input')).toHaveValue('')
  await expect(listOf(page)).toHaveCount(0)
})

test('depois de rolar, clicar num resultado do meio da lista abre justamente aquele', async ({ page, baseURL }) => {
  const ids = await realSessionIds(page, baseURL!)
  await searchWith(page, baseURL!, { count: 12, real: { 0: ids[0], 7: ids[1] } })
  const target = page.getByTestId('search-result').nth(7)
  await target.scrollIntoViewIfNeeded()
  expect(await listOf(page).evaluate((element) => element.scrollTop), 'a lista rolou').toBeGreaterThan(0)
  await target.click()
  await expect(page).toHaveURL(new RegExp(`/sessions/${ids[1]}`))
})
