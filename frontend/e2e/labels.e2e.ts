import type { Locator, Page } from '@playwright/test'
import { expect, test } from './fixtures'

// The texts below are the SCENARIO of scripts/e2e_server.py. Labels are global and the database
// lives through the whole run, so every test deletes the labels it made (afterEach).
const TITLE = 'Explique a estrutura do projeto'

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

async function createLabel(row: Locator, slug: string, color: string) {
  await openEditor(row)
  await row.getByTestId('label-new-color').fill(color)
  await row.getByTestId('label-new-slug').fill(slug)
  await row.getByTestId('label-new-save').click()
}

const badge = (scope: Locator | Page, slug: string) =>
  scope.locator(`[data-test="label-badge"][data-slug="${slug}"]`)

test('criar, aplicar, repetir slug, desmarcar, editar e apagar etiquetas', async ({ page, consoleErrors }) => {
  await openConversation(page)
  const row = await labelsRow(page)
  await expect(row).toContainText('Nenhuma')
  await expect(row.getByTestId('label-toggle')).toHaveText('Editar')

  // 1. Create "Urgente": the slug is normalized and the label is applied at once.
  await createLabel(row, 'Urgente', '#ef4444')
  await expect(badge(row, 'urgente')).toHaveText('urgente')
  await expect(row).not.toContainText('Nenhuma')
  await expect(badge(page.getByTestId('header-strip'), 'urgente')).toBeVisible()
  await expect(badge(page.getByRole('navigation', { name: 'Navegação' }).locator('..'), 'urgente').first()).toBeVisible()
  await expect(badge(page.getByTestId('header-strip'), 'urgente')).toHaveCSS('background-color', 'rgb(239, 68, 68)')

  // 2. A repeated slug shows the server error and creates nothing.
  await row.getByTestId('label-new-slug').fill('urgente')
  await row.getByTestId('label-new-save').click()
  await expect(row.getByTestId('label-error')).toHaveText('Já existe uma etiqueta com esse slug.')
  // The browser logs the 409 of the expected refusal; it is not an app error.
  expect(consoleErrors.splice(0).filter((m) => !m.includes('409'))).toEqual([])
  await expect(row.getByTestId('label-option')).toHaveCount(1)

  // 3. A second label, applied to the same conversation: both show; unchecking one drops only it.
  await row.getByTestId('label-new-slug').fill('backend')
  await row.getByTestId('label-new-color').fill('#1d4ed8')
  await row.getByTestId('label-new-save').click()
  await expect(row.getByTestId('label-error')).toHaveCount(0)
  await expect(row.getByTestId('label-option')).toHaveCount(2)
  await expect(badge(row, 'urgente')).toBeVisible()
  await expect(badge(row, 'backend')).toBeVisible()
  const urgenteBox = row.locator('[data-test="label-option"][data-slug="urgente"] input')
  await expect(urgenteBox).toBeChecked()
  await urgenteBox.uncheck()
  await expect(badge(row.getByTestId('label-badges'), 'urgente')).toHaveCount(0)
  await expect(badge(row.getByTestId('label-badges'), 'backend')).toBeVisible()
  await expect(badge(page.getByTestId('header-strip'), 'urgente')).toHaveCount(0)
  await expect(badge(page.getByTestId('header-strip'), 'backend')).toBeVisible()
  await urgenteBox.check()
  await expect(badge(page.getByTestId('header-strip'), 'urgente')).toBeVisible()

  // The conversations list shows both on the conversation's row, and reloading keeps them.
  await page.goto('/sessions')
  const listRow = page.getByTestId('conversation-row').filter({ hasText: TITLE })
  await expect(badge(listRow, 'urgente')).toBeVisible()
  await expect(badge(listRow, 'backend')).toBeVisible()
  await page.reload()
  await expect(badge(page.getByTestId('conversation-row').filter({ hasText: TITLE }), 'urgente')).toBeVisible()
  // The other conversations got none.
  await expect(page.getByTestId('conversation-row').filter({ hasText: 'Liste as tarefas pendentes' }).getByTestId('label-badge')).toHaveCount(0)

  // 4. Recolor and rename in Preferences; the badges follow, and survive a reload.
  await page.goto('/preferencias?aba=etiquetas')
  await expect(page.getByTestId('tab-labels')).toHaveAttribute('aria-selected', 'true')
  const prefRow = page.getByTestId('label-row').and(page.locator('[data-slug="urgente"]'))
  await expect(prefRow).toHaveCount(1)
  await prefRow.getByTestId('label-edit-color').fill('#facc15')
  await prefRow.getByTestId('label-edit-slug').fill('critico')
  await prefRow.getByTestId('label-save').click()
  await expect(page.locator('[data-test="label-row"][data-slug="critico"]')).toHaveCount(1)
  await expect(page.locator('[data-test="label-row"][data-slug="urgente"]')).toHaveCount(0)

  await page.goto('/sessions')
  const renamed = badge(page.getByTestId('conversation-row').filter({ hasText: TITLE }), 'critico')
  await expect(renamed).toHaveCSS('background-color', 'rgb(250, 204, 21)')
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
  await createLabel(row, 'achei-me', '#16a34a')
  await expect(badge(row, 'achei-me')).toBeVisible()

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
  await createLabel(row, longSlug, '#facc15')
  await expect(badge(row, longSlug)).toBeVisible()
  for (const [slug, color] of [['dois', '#1d4ed8'], ['tres', '#16a34a'], ['quatro', '#ef4444'], ['cinco', '#a855f7']]) {
    await row.getByTestId('label-new-slug').fill(slug)
    await row.getByTestId('label-new-color').fill(color)
    await row.getByTestId('label-new-save').click()
    await expect(badge(row, slug)).toBeVisible()
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

test('o texto do badge tem contraste legível com cor clara e escura, nos temas', async ({ page }) => {
  // WCAG relative luminance contrast of the badge's text over its own fill.
  const ratio = (badgeLocator: Locator) =>
    badgeLocator.evaluate((el) => {
      const parse = (s: string) => (s.match(/[\d.]+/g) ?? []).slice(0, 3).map(Number)
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

  await openConversation(page)
  const row = await labelsRow(page)
  await createLabel(row, 'clara', '#facc15')
  await expect(badge(row, 'clara')).toBeVisible()
  await row.getByTestId('label-new-slug').fill('escura')
  await row.getByTestId('label-new-color').fill('#1d4ed8')
  await row.getByTestId('label-new-save').click()
  await expect(badge(row, 'escura')).toBeVisible()

  for (const theme of ['Maestro', 'Dracula', 'Monokai Ristretto']) {
    await page.goto('/preferencias')
    await page.locator('[data-test="theme-option"]', { hasText: theme }).click()
    await page.goto('/sessions')
    const listRow = page.getByTestId('conversation-row').filter({ hasText: TITLE })
    for (const slug of ['clara', 'escura']) {
      expect(await ratio(badge(listRow, slug)), `${slug} em ${theme}`).toBeGreaterThanOrEqual(4.5)
    }
  }
  await page.goto('/preferencias')
  await page.locator('[data-test="theme-option"]', { hasText: 'Maestro' }).click()
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

  // Tab leaves the button and lands on the form fields, which have accessible names.
  await expect(row.getByLabel('Slug da nova etiqueta')).toBeVisible()
  await expect(row.getByLabel('Cor da nova etiqueta')).toBeVisible()
  await row.getByLabel('Slug da nova etiqueta').fill('teclado')
  await page.keyboard.press('Enter')
  const option = row.locator('[data-test="label-option"][data-slug="teclado"] input')
  await expect(option).toBeChecked()

  // The checkbox is reachable and toggles with the space bar.
  await option.focus()
  await expect(option).toBeFocused()
  await page.keyboard.press('Space')
  await expect(option).not.toBeChecked()
  await expect(badge(page.getByTestId('header-strip'), 'teclado')).toHaveCount(0)
  await option.check()
  await expect(badge(page.getByTestId('header-strip'), 'teclado')).toBeVisible()

  // Escape-free close with the button.
  await toggle.focus()
  await page.keyboard.press('Enter')
  await expect(toggle).toHaveAttribute('aria-expanded', 'false')
  await expect(row.getByTestId('label-option')).toHaveCount(0)
})

// The controls stay enabled while a request runs (`aria-busy` on the row instead), so the browser
// does not drop the keyboard focus and the next Space still works.
test('o foco continua na caixa depois de marcar com o teclado', async ({ page }) => {
  await openConversation(page)
  const row = await labelsRow(page)
  await createLabel(row, 'foco', '#16a34a')
  const option = row.locator('[data-test="label-option"][data-slug="foco"] input')
  await expect(option).toBeChecked()
  await option.focus()
  await page.keyboard.press('Space')
  await expect(option).not.toBeChecked()
  await expect(row).not.toHaveAttribute('aria-busy', 'true')
  await expect(option).toBeFocused()
  await page.keyboard.press('Space')
  await expect(option).toBeChecked()
  await expect(row).not.toHaveAttribute('aria-busy', 'true')
  await expect(option).toBeFocused()
})
