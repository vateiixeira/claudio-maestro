import type { APIRequestContext, Page } from '@playwright/test'
import { expect, test } from './fixtures'

// Labels are global and the database lives through the whole run: every test deletes what it made.
const TITLE = 'Explique a estrutura do projeto'
const GREEN = '#a9dc76'

let headers: Record<string, string>
test.beforeEach(({ baseURL }) => {
  headers = { 'X-Maestro': '1', Origin: baseURL! }
})
test.afterEach(async ({ page }) => {
  const list = await page.request.get('/api/labels', { headers })
  for (const label of (await list.json()) as { id: number }[]) {
    await page.request.delete(`/api/labels/${label.id}`, { headers })
  }
})

type Label = { id: number; slug: string; color: string }
const listLabels = async (request: APIRequestContext) => (await (await request.get('/api/labels', { headers })).json()) as Label[]

async function makeLabel(request: APIRequestContext, slug: string, color = '#9e9d9d') {
  const made = await request.post('/api/labels', { headers, data: { slug, color } })
  expect(made.status()).toBe(201)
  return (await made.json()) as Label
}

/** Opens the tab with the conversations loaded, so the usage column and the "Sem uso" group are known. */
async function openTab(page: Page) {
  await page.goto('/preferencias?aba=etiquetas')
  await expect(page.getByTestId('tab-labels')).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByTestId('label-usage').first()).not.toHaveText('')
}

test('renomear salva ao sair do campo, e Esc desfaz a digitação', async ({ page }) => {
  await makeLabel(page.request, 'antigo')
  await openTab(page)
  const row = page.locator('[data-test="label-row"][data-slug="antigo"]')
  const field = row.getByTestId('label-edit-slug')
  await expect(page.getByTestId('label-save')).toHaveCount(0)

  // Esc drops what was typed and saves nothing.
  await field.fill('descartado')
  await field.press('Escape')
  await expect(field).toHaveValue('antigo')
  await expect.poll(async () => (await listLabels(page.request)).map((l) => l.slug)).toEqual(['antigo'])

  // Leaving the field saves the new name (normalized).
  await field.fill('Novo-Nome')
  await field.blur()
  const renamed = page.locator('[data-test="label-row"][data-slug="novo-nome"]')
  await expect(renamed).toHaveCount(1)
  await expect.poll(async () => (await listLabels(page.request)).map((l) => l.slug)).toEqual(['novo-nome'])

  // Enter saves too, and the name survives a reload.
  await renamed.getByTestId('label-edit-slug').fill('final')
  await renamed.getByTestId('label-edit-slug').press('Enter')
  await expect(page.locator('[data-test="label-row"][data-slug="final"]')).toHaveCount(1)
  await page.reload()
  await expect(page.locator('[data-test="label-row"][data-slug="final"]')).toHaveCount(1)
})

test('trocar a cor pela paleta salva na hora e fecha a paleta', async ({ page }) => {
  const label = await makeLabel(page.request, 'colorida')
  await openTab(page)
  const row = page.locator('[data-test="label-row"][data-slug="colorida"]')
  const dot = row.getByTestId('label-edit-color')
  await expect(dot).toHaveAttribute('aria-expanded', 'false')
  await dot.click()
  await expect(dot).toHaveAttribute('aria-expanded', 'true')
  await row.getByTestId('palette-color').and(page.locator(`[data-color="${GREEN}"]`)).click()
  await expect(row.getByTestId('palette-color')).toHaveCount(0)
  await expect(dot).toHaveCSS('background-color', 'rgb(169, 220, 118)')
  await expect.poll(async () => (await listLabels(page.request)).find((l) => l.id === label.id)?.color).toBe(GREEN)
  await page.reload()
  await expect(page.locator('[data-test="label-row"][data-slug="colorida"]').getByTestId('label-edit-color')).toHaveCSS('background-color', 'rgb(169, 220, 118)')
})

test('criar pela linha de cima, e apagar as sem uso pede confirmação e preserva as usadas', async ({ page }) => {
  // One label in use, so the "Sem uso" group has to leave it alone.
  const used = await makeLabel(page.request, 'em-uso')
  const sessions = (await (await page.request.get('/api/sessions', { headers })).json()) as { session_id: string; title: string }[]
  const target = sessions.find((s) => s.title === TITLE)!
  await page.request.put(`/api/sessions/${target.session_id}/labels`, { headers, data: { label_ids: [used.id] } })
  await openTab(page)

  // Creating from the top row: Enter in the name field, the selected swatch decides the color.
  await page.getByTestId('label-create-slug').fill('sobra-um')
  await page.getByTestId('label-create-slug').press('Enter')
  await expect(page.locator('[data-test="label-row"][data-slug="sobra-um"]')).toHaveCount(1)
  await page.getByTestId('label-create-slug').fill('sobra-dois')
  await page.getByTestId('label-create').click()
  await expect(page.locator('[data-test="label-row"][data-slug="sobra-dois"]')).toHaveCount(1)

  const group = page.getByTestId('label-unused-group')
  await expect(group.getByTestId('label-row')).toHaveCount(2)
  await expect(group.getByTestId('label-usage').first()).toHaveText('sem uso')
  await expect(page.locator('[data-test="label-row"][data-slug="em-uso"]')).toContainText('1 conversa')
  await expect(group.locator('[data-slug="em-uso"]')).toHaveCount(0)

  // The confirmation lists what goes away; cancelling keeps everything.
  await group.getByTestId('label-delete-unused').click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toContainText('Apagar 2 etiquetas sem uso?')
  await expect(dialog.getByTestId('label-delete-unused-list')).toContainText('sobra-um')
  await expect(dialog.getByTestId('label-delete-unused-list')).toContainText('sobra-dois')
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  expect((await listLabels(page.request)).map((l) => l.slug).sort()).toEqual(['em-uso', 'sobra-dois', 'sobra-um'])

  await group.getByTestId('label-delete-unused').click()
  await page.getByRole('dialog').getByTestId('confirm-ok').click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.getByTestId('label-unused-group')).toHaveCount(0)
  await expect(page.locator('[data-test="label-row"]')).toHaveCount(1)
  await expect(page.locator('[data-test="label-row"][data-slug="em-uso"]')).toHaveCount(1)
  expect((await listLabels(page.request)).map((l) => l.slug)).toEqual(['em-uso'])
})
