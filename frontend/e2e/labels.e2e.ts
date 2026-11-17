import type { Locator, Page } from '@playwright/test'
import { expect, test } from './fixtures'

// The texts below are the SCENARIO of scripts/e2e_server.py. Labels are global and the database
// lives through the whole run, so every test deletes the labels it made (afterEach).
const TITLE = 'Explique a estrutura do projeto'
// Colors of the palette (LABEL_PALETTE in src/labelColor.ts) and the dot color each one gives.
const PINK = '#ff6188'
const PINK_RGB = 'rgb(255, 97, 136)'
const YELLOW = '#ffd866'
const GREEN = '#a9dc76'
const CYAN = '#78dce8'
const VIOLET = '#ab9df2'

test.afterEach(async ({ page, baseURL }) => {
  const headers = { 'X-Maestro': '1', Origin: baseURL! }
  const list = await page.request.get('/api/labels', { headers })
  for (const label of (await list.json()) as { id: number }[]) {
    await page.request.delete(`/api/labels/${label.id}`, { headers })
  }
})

async function openConversation(page: Page) {
  await page.goto('/sessions')
  await page.getByTestId('row-link').filter({ hasText: TITLE }).first().click()
  await expect(page).toHaveURL(/\/sessions\/[0-9a-f-]+/)
}

/** The details panel's "Etiquetas" row, opening the panel when it starts closed. */
async function labelsRow(page: Page): Promise<Locator> {
  const row = page.getByTestId('prop-labels')
  if (!(await row.isVisible())) await page.getByTestId('toggle-details').first().click()
  await expect(row).toBeVisible()
  return row
}

async function openEditor(row: Locator) {
  const toggle = row.getByTestId('label-toggle')
  if ((await toggle.getAttribute('aria-expanded')) !== 'true') await toggle.click()
  await expect(toggle).toHaveAttribute('aria-expanded', 'true')
}

/** Types the name in the combobox, picks a swatch of the palette and creates the label (it is applied at once). */
async function createLabel(row: Locator, slug: string, color: string) {
  await openEditor(row)
  await row.getByTestId('label-search').fill(slug)
  await row.getByTestId('label-new-color').locator(`[data-color="${color}"]`).click()
  await row.getByTestId('label-new-save').click()
  await expect(chip(row, slug.toLowerCase())).toBeVisible()
}

/** A chip of the field: how an applied label shows while the editor is open. */
const chip = (scope: Locator | Page, slug: string) => scope.locator(`[data-test="label-chip"][data-slug="${slug}"]`)
const option = (scope: Locator | Page, slug: string) => scope.locator(`[data-test="label-option"][data-slug="${slug}"]`)

const badge = (scope: Locator | Page, slug: string) =>
  scope.locator(`[data-test="label-badge"][data-slug="${slug}"]`)

test('criar, aplicar, desmarcar, editar e apagar etiquetas', async ({ page }) => {
  await openConversation(page)
  const row = await labelsRow(page)
  await expect(row).toContainText('Nenhuma')
  await expect(row.getByTestId('label-toggle')).toHaveText('Editar')

  // 1. Create "Urgente": the slug is normalized and the label is applied at once.
  await createLabel(row, 'Urgente', PINK)
  await expect(chip(row, 'urgente')).toContainText('urgente')
  const strip = page.getByTestId('header-strip')
  await expect(badge(strip, 'urgente')).toBeVisible()
  await expect(badge(page.getByRole('navigation', { name: 'Navegação' }).locator('..'), 'urgente').first()).toBeVisible()
  // The badge carries the label's color in its dot (the fill is only a tint of it).
  await expect(badge(strip, 'urgente').getByTestId('label-dot')).toHaveCSS('background-color', PINK_RGB)
  // The name is taken: typing it again offers no "Criar etiqueta", only the existing option.
  await row.getByTestId('label-search').fill('urgente')
  await expect(option(row, 'urgente')).toHaveCount(1)
  await expect(row.getByTestId('label-new-save')).toHaveCount(0)
  await row.getByTestId('label-search').fill('')

  // 2. A second label, with a color outside the palette ("Outra…"): both stay applied.
  await row.getByTestId('label-search').fill('backend')
  // The native picker is hidden behind "Outra…": set its value the way the browser does when a color is chosen.
  await row.getByTestId('label-new-color').locator('input[type="color"]').evaluate((el: HTMLInputElement) => {
    el.value = '#1d4ed8'
    el.dispatchEvent(new Event('input', { bubbles: true }))
  })
  await expect(row.getByTestId('palette-custom')).toHaveAttribute('aria-pressed', 'true')
  await row.getByTestId('label-new-save').click()
  await expect(chip(row, 'backend')).toBeVisible()
  await expect(badge(strip, 'backend').getByTestId('label-dot')).toHaveCSS('background-color', 'rgb(29, 78, 216)')
  await expect(row.getByTestId('label-option')).toHaveCount(2)
  await expect(row.getByTestId('label-error')).toHaveCount(0)

  // 3. Unmarking one in the list drops only it, in the field and in the header; marking brings it back.
  await option(row, 'urgente').click()
  await expect(option(row, 'urgente')).toHaveAttribute('aria-selected', 'false')
  await expect(chip(row, 'urgente')).toHaveCount(0)
  await expect(chip(row, 'backend')).toBeVisible()
  await expect(badge(strip, 'urgente')).toHaveCount(0)
  await expect(badge(strip, 'backend')).toBeVisible()
  await option(row, 'urgente').click()
  await expect(option(row, 'urgente')).toHaveAttribute('aria-selected', 'true')
  await expect(badge(strip, 'urgente')).toBeVisible()
  // The chip's "x" also takes it off.
  await chip(row, 'urgente').getByTestId('label-chip-remove').click()
  await expect(chip(row, 'urgente')).toHaveCount(0)
  await option(row, 'urgente').click()
  await expect(chip(row, 'urgente')).toBeVisible()

  // The conversations list shows both on the conversation's row, and reloading keeps them.
  await page.goto('/sessions')
  const listRow = page.getByTestId('conversation-row').filter({ hasText: TITLE })
  await expect(badge(listRow, 'urgente')).toBeVisible()
  await expect(badge(listRow, 'backend')).toBeVisible()
  await page.reload()
  await expect(badge(page.getByTestId('conversation-row').filter({ hasText: TITLE }), 'urgente')).toBeVisible()
  // The other conversations got none.
  await expect(page.getByTestId('conversation-row').filter({ hasText: 'Liste as tarefas pendentes' }).getByTestId('label-badge')).toHaveCount(0)

  // 4. Recolor and rename in Preferences: both save by themselves (no save button), and the badges follow.
  await page.goto('/preferencias?aba=etiquetas')
  await expect(page.getByTestId('tab-labels')).toHaveAttribute('aria-selected', 'true')
  const prefRow = page.getByTestId('label-row').and(page.locator('[data-slug="urgente"]'))
  await expect(prefRow).toHaveCount(1)
  await expect(page.getByTestId('label-save')).toHaveCount(0)
  await prefRow.getByTestId('label-edit-color').click()
  await prefRow.getByTestId('palette-color').and(page.locator(`[data-color="${YELLOW}"]`)).click()
  await expect(prefRow.getByTestId('label-edit-color')).toHaveCSS('background-color', 'rgb(255, 216, 102)')
  await prefRow.getByTestId('label-edit-slug').fill('critico')
  await prefRow.getByTestId('label-edit-slug').press('Enter')
  await expect(page.locator('[data-test="label-row"][data-slug="critico"]')).toHaveCount(1)
  await expect(page.locator('[data-test="label-row"][data-slug="urgente"]')).toHaveCount(0)

  await page.goto('/sessions')
  const renamed = badge(page.getByTestId('conversation-row').filter({ hasText: TITLE }), 'critico')
  await expect(renamed.getByTestId('label-dot')).toHaveCSS('background-color', 'rgb(255, 216, 102)')
  await expect(badge(page, 'urgente')).toHaveCount(0)
  await page.reload()
  await expect(renamed).toBeVisible()

  // 5. Delete in Preferences, with the confirmation (it tells how many conversations lose it).
  await page.goto('/preferencias?aba=etiquetas')
  const critico = page.locator('[data-test="label-row"][data-slug="critico"]')
  await critico.getByTestId('label-delete').click()
  await expect(critico).toContainText('1 conversa')
  await critico.getByTestId('label-delete-confirm').click()
  await expect(critico).toHaveCount(0)

  await page.goto('/sessions')
  await expect(page.getByTestId('conversation-row').first()).toBeVisible()
  await expect(badge(page, 'critico')).toHaveCount(0)
  await expect(badge(page, 'backend').first()).toBeVisible() // untouched
  await page.goto(page.url())
  await openConversation(page)
  const row2 = await labelsRow(page)
  await expect(badge(row2, 'critico')).toHaveCount(0)
  await expect(badge(page.getByTestId('header-strip'), 'critico')).toHaveCount(0)
  await expect(badge(page.getByTestId('header-strip'), 'backend')).toBeVisible()
})

test('as etiquetas aparecem na Caixa de entrada, no Painel e na busca', async ({ page }) => {
  await openConversation(page)
  const row = await labelsRow(page)
  await createLabel(row, 'achei-me', GREEN)

  await page.goto('/inbox')
  await expect(page.getByRole('heading', { name: 'Inbox', level: 1 })).toBeVisible()
  await page.getByRole('tab', { name: 'Todas' }).or(page.getByRole('button', { name: 'Todas' })).first().click()
  await expect(badge(page.getByTestId('conversation-row').filter({ hasText: TITLE }), 'achei-me')).toBeVisible()

  // Dashboard: the seeded conversations are not running, so the scenario has no NowCard to check.

  // The sidebar search finds the conversation by the label's slug and shows its badge.
  await page.getByTestId('search-input').fill('achei')
  const result = page.getByTestId('search-result').filter({ hasText: TITLE })
  await expect(result).toHaveCount(1)
  await expect(badge(result, 'achei-me')).toBeVisible()
})

test('slug de 32 caracteres e várias etiquetas não estouram a linha, em tela larga e estreita', async ({ page }) => {
  await openConversation(page)
  const row = await labelsRow(page)
  const longSlug = 'a'.repeat(31) + 'z'
  await createLabel(row, longSlug, YELLOW)
  for (const [slug, color] of [['dois', CYAN], ['tres', GREEN], ['quatro', PINK], ['cinco', VIOLET]]) {
    await createLabel(row, slug, color)
  }
  await expect(row.getByTestId('label-error')).toHaveCount(0)

  const noOverflow = async () => {
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
    expect(overflow, 'rolagem horizontal da página').toBeLessThanOrEqual(0)
  }
  const insideItsCard = async (card: Locator, scope: Locator) => {
    const box = await card.boundingBox()
    expect(box).not.toBeNull()
    for (const b of await scope.getByTestId('label-badge').all()) {
      const bb = await b.boundingBox()
      if (!bb) continue
      expect(bb.x + bb.width, 'badge vaza à direita do cartão').toBeLessThanOrEqual(box!.x + box!.width + 1)
    }
  }

  for (const size of [{ width: 1440, height: 900 }, { width: 820, height: 800 }]) {
    await page.setViewportSize(size)
    await page.goto('/sessions')
    const listRow = page.getByTestId('conversation-row').filter({ hasText: TITLE })
    await expect(listRow).toBeVisible()
    // Up to three badges plus "+N" in the list; the long slug is truncated, not wrapped out.
    await expect(listRow.getByTestId('label-badge')).toHaveCount(3)
    await expect(listRow.getByTestId('label-more')).toHaveText('+2')
    await noOverflow()
    await insideItsCard(listRow, listRow)
    // Title still readable, and the right columns on the same line as the title.
    const title = listRow.getByTestId('row-link')
    await expect(title).toBeVisible()
    const t = (await title.boundingBox())!
    expect(t.width, 'título ainda tem espaço').toBeGreaterThan(40)
    const r = (await listRow.boundingBox())!
    expect(r.height, 'a linha não cresce em várias linhas').toBeLessThan(80)
    const actions = listRow.getByTestId('row-actions')
    if (await actions.count()) {
      const a = await actions.boundingBox()
      if (a) expect(a.x + a.width).toBeLessThanOrEqual(r.x + r.width + 1)
    }

    // The conversation header.
    await openConversationNoReset(page)
    const strip = page.getByTestId('header-strip')
    await expect(strip).toBeVisible()
    await noOverflow()
    await insideItsCard(strip, strip)
  }
})

async function openConversationNoReset(page: Page) {
  await page.getByTestId('conversation-row').filter({ hasText: TITLE }).getByTestId('row-link').click()
  await expect(page).toHaveURL(/\/sessions\/[0-9a-f-]+/)
}

test('o texto do selo tem contraste legível sobre o fundo tingido, com cor clara e escura, nos oito temas', async ({ page, baseURL }) => {
  // WCAG relative luminance contrast of the badge's text over its own fill. The fill is a color-mix(),
  // which Chrome reports as color(srgb r g b) with channels from 0 to 1.
  const ratio = (badgeLocator: Locator) =>
    badgeLocator.evaluate((el) => {
      const parse = (s: string) => {
        const numbers = (s.match(/[\d.]+/g) ?? []).slice(0, 3).map(Number)
        return s.startsWith('color(') ? numbers.map((n) => n * 255) : numbers
      }
      const lum = ([r, g, b]: number[]) => {
        const f = (v: number) => {
          const c = v / 255
          return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
        }
        return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)
      }
      const style = getComputedStyle(el)
      const a = lum(parse(style.color))
      const b = lum(parse(style.backgroundColor))
      return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05)
    })

  const headers = { 'X-Maestro': '1', Origin: baseURL! }
  const ids: number[] = []
  for (const [slug, color] of [['clara', YELLOW], ['escura', '#1d4ed8'], ['rosa', PINK]]) {
    const made = await page.request.post('/api/labels', { headers, data: { slug, color } })
    ids.push(((await made.json()) as { id: number }).id)
  }
  const sessions = (await (await page.request.get('/api/sessions', { headers })).json()) as { session_id: string; title: string }[]
  const target = sessions.find((s) => s.title === TITLE)!
  await page.request.put(`/api/sessions/${target.session_id}/labels`, { headers, data: { label_ids: ids } })

  try {
    for (const theme of ['Maestro', 'Dracula', 'Monokai Pro', 'Monokai Machine', 'Monokai Octagon', 'Monokai Ristretto', 'Monokai Spectrum', 'Monokai Classic']) {
      await page.goto('/preferencias')
      await page.locator('[data-test="theme-option"]', { hasText: theme }).click()
      await page.goto('/sessions')
      const listRow = page.getByTestId('conversation-row').filter({ hasText: TITLE })
      for (const slug of ['clara', 'escura', 'rosa']) {
        expect(await ratio(badge(listRow, slug)), `${slug} em ${theme}`).toBeGreaterThanOrEqual(4.5)
      }
    }
  } finally {
    await page.goto('/preferencias')
    await page.locator('[data-test="theme-option"]', { hasText: 'Maestro' }).click()
  }
})

test('teclado e acessibilidade do seletor de etiquetas', async ({ page }) => {
  await openConversation(page)
  const row = await labelsRow(page)
  const toggle = row.getByTestId('label-toggle')
  await expect(toggle).toHaveAttribute('aria-expanded', 'false')
  await expect(toggle).not.toHaveAttribute('aria-controls', /.+/)
  await toggle.focus()
  await page.keyboard.press('Enter')
  await expect(toggle).toHaveAttribute('aria-expanded', 'true')
  await expect(toggle).toHaveText('Fechar')
  const controls = await toggle.getAttribute('aria-controls')
  await expect(page.locator(`[id="${controls}"]`)).toBeVisible()

  // Opening puts the focus in the combobox, which has an accessible name and owns the list.
  const search = row.getByRole('combobox', { name: 'Procurar ou criar etiqueta' })
  await expect(search).toBeFocused()
  await expect(row.getByRole('listbox', { name: 'Etiquetas' })).toBeAttached()
  await page.keyboard.type('teclado')
  await expect(row.getByTestId('label-new-save')).toBeVisible()
  // Enter with nothing highlighted creates the label and applies it.
  await page.keyboard.press('Enter')
  await expect(chip(row, 'teclado')).toBeVisible()
  await expect(badge(page.getByTestId('header-strip'), 'teclado')).toBeVisible()
  await expect(search).toHaveValue('')

  // The arrows highlight a row (aria-activedescendant) and Enter marks or unmarks it.
  await page.keyboard.press('ArrowDown')
  const opt = option(row, 'teclado')
  await expect(opt).toHaveAttribute('data-active', 'true')
  await expect(search).toHaveAttribute('aria-activedescendant', (await opt.getAttribute('id'))!)
  await page.keyboard.press('Enter')
  await expect(opt).toHaveAttribute('aria-selected', 'false')
  await expect(chip(row, 'teclado')).toHaveCount(0)
  await expect(badge(page.getByTestId('header-strip'), 'teclado')).toHaveCount(0)
  await page.keyboard.press('Enter')
  await expect(opt).toHaveAttribute('aria-selected', 'true')
  await expect(badge(page.getByTestId('header-strip'), 'teclado')).toBeVisible()

  // Escape closes the panel and gives the focus back to the button.
  await page.keyboard.press('Escape')
  await expect(toggle).toHaveAttribute('aria-expanded', 'false')
  await expect(toggle).toBeFocused()
  await expect(row.getByTestId('label-option')).toHaveCount(0)
})

// The controls stay enabled while a request runs (`aria-busy` on the row instead), so the browser
// does not drop the keyboard focus and the next Enter still works.
test('o foco continua no campo depois de marcar com o teclado', async ({ page }) => {
  await openConversation(page)
  const row = await labelsRow(page)
  await createLabel(row, 'foco', GREEN)
  const search = row.getByTestId('label-search')
  await search.focus()
  await page.keyboard.press('ArrowDown')
  await page.keyboard.press('Enter')
  await expect(chip(row, 'foco')).toHaveCount(0)
  await expect(row).not.toHaveAttribute('aria-busy', 'true')
  await expect(search).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(chip(row, 'foco')).toBeVisible()
  await expect(row).not.toHaveAttribute('aria-busy', 'true')
  await expect(search).toBeFocused()
})

test('a paleta do seletor aparece só ao criar, e filtrar mostra o trecho achado e a contagem de uso', async ({ page }) => {
  await openConversation(page)
  const row = await labelsRow(page)
  await createLabel(row, 'backend', CYAN)
  await createLabel(row, 'frontend', GREEN)
  const search = row.getByTestId('label-search')
  // Nothing typed: no palette. A name that matches nothing: the create row and the palette.
  await expect(row.getByTestId('label-new-color')).toHaveCount(0)
  await search.fill('zzz')
  await expect(row.getByTestId('label-option')).toHaveCount(0)
  await expect(row.getByTestId('label-new-color').getByTestId('palette-color')).toHaveCount(7)
  await expect(row.getByTestId('palette-custom')).toHaveText('Outra…')
  // A partial name filters the list and highlights what matched; the count says how many conversations use it.
  await search.fill('end')
  await expect(row.getByTestId('label-option')).toHaveCount(2)
  await expect(option(row, 'backend').locator('mark')).toHaveText('end')
  await expect(option(row, 'backend').getByTestId('label-count')).toHaveText('1 conversa')
})

test('no menu lateral e na busca, as etiquetas ficam numa linha abaixo do título, alinhadas a ele', async ({ page }) => {
  await openConversation(page)
  const row = await labelsRow(page)
  await createLabel(row, 'primeira', CYAN)
  const side = page.locator('a', { has: page.getByTestId('row-title') }).filter({ hasText: TITLE }).first()
  await expect(side.getByTestId('row-labels')).toBeVisible()
  for (const [slug, color] of [['segunda', GREEN], ['terceira', PINK], ['quarta', VIOLET]]) {
    await createLabel(row, slug, color)
  }
  await expect(side.getByTestId('row-labels').getByTestId('label-badge')).toHaveCount(4)
  await expect(side.getByTestId('row-labels').getByTestId('label-more')).toHaveCount(0)
  // Badges are not on the title line.
  await expect(side.getByTestId('row-line').getByTestId('label-badge')).toHaveCount(0)

  const title = (await side.getByTestId('row-title').boundingBox())!
  const labels = (await side.getByTestId('row-labels').boundingBox())!
  const link = (await side.boundingBox())!
  expect(labels.y, 'tags abaixo do título').toBeGreaterThanOrEqual(title.y + title.height - 1)
  expect(Math.abs(labels.x - title.x), 'tags alinhadas à borda esquerda do título').toBeLessThanOrEqual(1)
  expect(labels.x + labels.width, 'tags dentro da linha').toBeLessThanOrEqual(link.x + link.width + 1)
  expect(labels.y + labels.height, 'tags dentro da linha, com folga embaixo').toBeLessThan(link.y + link.height)

  // The search result: the labels on their own line, between the title and the project line.
  await page.getByTestId('search-input').fill('primeira')
  const result = page.getByTestId('search-result').filter({ hasText: TITLE })
  await expect(result).toHaveCount(1)
  const found = result.getByTestId('search-labels')
  await expect(found.getByTestId('label-badge')).toHaveCount(4)
  const resultBox = (await result.boundingBox())!
  const foundBox = (await found.boundingBox())!
  expect(foundBox.x + foundBox.width).toBeLessThanOrEqual(resultBox.x + resultBox.width + 1)
})

const SECOND_TITLE = 'Liste as tarefas pendentes'

async function labelAll(page: Page, baseURL: string, slugs: string[], title: string) {
  const headers = { 'X-Maestro': '1', Origin: baseURL }
  const ids: number[] = []
  for (const slug of slugs) {
    const made = await page.request.post('/api/labels', { headers, data: { slug, color: '#1d4ed8' } })
    ids.push(((await made.json()) as { id: number }).id)
  }
  const sessions = (await (await page.request.get('/api/sessions', { headers })).json()) as { session_id: string; title: string }[]
  const target = sessions.find((s) => s.title === title)!
  await page.request.put(`/api/sessions/${target.session_id}/labels`, { headers, data: { label_ids: ids } })
}

test('conversa aninhada: sem tag mantém a altura, com tag ganha segunda linha alinhada ao título', async ({ page, baseURL }) => {
  await labelAll(page, baseURL!, ['um'], TITLE)
  await labelAll(page, baseURL!, ['m1', 'm2', 'm3', 'm4'], 'Investigue o módulo de pagamentos')
  await page.goto('/inbox')
  const nested = (title: string) => page.getByTestId('project-session').filter({ hasText: title })

  const plain = (await nested(SECOND_TITLE).boundingBox())!
  expect(plain.height, 'linha sem tag mantém ~28px').toBeLessThanOrEqual(29)
  await expect(nested(SECOND_TITLE).getByTestId('row-labels')).toHaveCount(0)

  for (const [title, count] of [[TITLE, 1], ['Investigue o módulo de pagamentos', 4]] as const) {
    const row = nested(title)
    const labels = row.getByTestId('row-labels')
    await expect(labels.getByTestId('label-badge')).toHaveCount(count)
    const box = (await row.boundingBox())!
    const line = (await row.getByTestId('row-line').boundingBox())!
    const name = (await row.getByTestId('row-title').boundingBox())!
    const second = (await labels.boundingBox())!
    const icon = (await row.locator('svg').first().boundingBox())!
    expect(box.height, 'linha com tag é mais alta').toBeGreaterThan(plain.height + 10)
    expect(Math.abs(second.x - name.x), 'segunda linha alinhada ao título').toBeLessThanOrEqual(1)
    expect(second.y).toBeGreaterThanOrEqual(line.y + line.height - 1)
    expect(second.y + second.height, 'folga embaixo').toBeLessThan(box.y + box.height)
    expect(Math.abs(icon.y + icon.height / 2 - (line.y + line.height / 2)), 'ícone centrado na linha 1').toBeLessThanOrEqual(1.5)
    await expect(row.getByTestId('row-age')).toBeVisible()
    expect(second.x + second.width).toBeLessThanOrEqual(box.x + box.width + 1)
  }
  await expect(nested('Investigue').getByTestId('label-more')).toHaveCount(0)
})

test('conversa avulsa (lane "Para revisar") com tags: segunda linha alinhada e menu de contexto abre e fecha', async ({ page, baseURL }) => {
  await labelAll(page, baseURL!, ['x1', 'x2'], SECOND_TITLE)
  await page.goto('/inbox')
  const nested = page.getByTestId('project-session').filter({ hasText: SECOND_TITLE })
  try {
    await nested.click({ button: 'right' })
    const popover = page.getByTestId('mark-popover')
    await expect(popover).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(popover).toHaveCount(0)

    await nested.click({ button: 'right' })
    await page.getByTestId('mark-review').click()
    const row = page.getByTestId('lane-review-row').filter({ hasText: SECOND_TITLE })
    await expect(row).toBeVisible()
    const name = (await row.getByTestId('row-title').boundingBox())!
    const second = (await row.getByTestId('row-labels').boundingBox())!
    const box = (await row.boundingBox())!
    expect(Math.abs(second.x - name.x)).toBeLessThanOrEqual(1)
    expect(second.y).toBeGreaterThanOrEqual(name.y + name.height - 1)
    expect(second.y + second.height).toBeLessThan(box.y + box.height)
    await expect(row.getByTestId('row-age')).toBeVisible()
  } finally {
    await nested.click({ button: 'right' })
    await page.getByTestId('mark-clear').click()
    await expect(page.getByTestId('lane-review-row')).toHaveCount(0)
  }
})

test('tag com slug longo aparece inteira, quebrando a linha sem estourar a barra', async ({ page, baseURL }) => {
  const long = 'subir-e-acompanhar-deploy-em-pro'
  await labelAll(page, baseURL!, [long, 'b'], TITLE)
  await page.goto('/inbox')
  const row = page.getByTestId('project-session').filter({ hasText: TITLE })
  await expect(row.getByTestId('row-labels').getByTestId('label-badge')).toHaveCount(2)
  const badge = row.locator(`[data-test="label-badge"][data-slug="${long}"]`)
  await expect(badge).toHaveText(long)
  expect(await badge.evaluate((el) => el.scrollWidth <= el.clientWidth), 'nome inteiro, sem corte').toBe(true)
  const box = (await row.boundingBox())!
  for (const slug of [long, 'b']) {
    const b = (await badgeBox(row, slug))!
    expect(b.x + b.width, `${slug} dentro da barra`).toBeLessThanOrEqual(box.x + box.width + 1)
    expect(b.y + b.height, `${slug} dentro da linha`).toBeLessThan(box.y + box.height)
  }
})

async function badgeBox(scope: Locator, slug: string) {
  return scope.locator(`[data-test="label-badge"][data-slug="${slug}"]`).boundingBox()
}

test('busca: resultado sem tag não deixa linha vazia', async ({ page, baseURL }) => {
  await labelAll(page, baseURL!, ['achada'], TITLE)
  await page.goto('/inbox')
  await page.getByTestId('search-input').fill('pendentes')
  const plain = page.getByTestId('search-result').filter({ hasText: SECOND_TITLE })
  await expect(plain).toHaveCount(1)
  await expect(plain.getByTestId('search-labels')).toHaveCount(0)
  await page.getByTestId('search-input').fill('estrutura do projeto')
  const tagged = page.getByTestId('search-result').filter({ hasText: TITLE })
  await expect(tagged.getByTestId('search-labels').getByTestId('label-badge')).toHaveCount(1)
  const t = (await tagged.getByTestId('search-labels').boundingBox())!
  const title = (await tagged.locator('span').first().boundingBox())!
  expect(t.y).toBeGreaterThanOrEqual(title.y + title.height - 1)
})
