import { expect, test } from './fixtures'

const background = (page: import('@playwright/test').Page) =>
  page.evaluate(() => getComputedStyle(document.body).backgroundColor)
const option = (page: import('@playwright/test').Page, name: string) =>
  page.locator('[data-test="theme-option"]', { hasText: name })

test('trocar o tema muda as cores do app e a escolha sobrevive ao recarregar', async ({ page }) => {
  await page.goto('/preferencias')
  await expect(page.getByRole('heading', { name: 'Preferências', level: 1 })).toBeVisible()

  // Maestro (padrão): fundo #0b0b0c e nenhum data-theme.
  await expect(page.locator('html')).not.toHaveAttribute('data-theme', /.+/)
  expect(await background(page)).toBe('rgb(11, 11, 12)')
  await expect(option(page, 'Maestro').locator('input')).toBeChecked()

  // Dracula: fundo #21222c.
  await option(page, 'Dracula').click()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dracula')
  expect(await background(page)).toBe('rgb(33, 34, 44)')
  await expect(option(page, 'Dracula').locator('input')).toBeChecked()

  // A escolha vale depois de recarregar, já na primeira pintura.
  await page.reload()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dracula')
  expect(await background(page)).toBe('rgb(33, 34, 44)')
  await expect(option(page, 'Dracula').locator('input')).toBeChecked()

  // Um Monokai: Monokai Pro, fundo #221f22.
  await option(page, 'Monokai Pro').click()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'monokai-pro')
  expect(await background(page)).toBe('rgb(34, 31, 34)')

  // Voltar ao Maestro tira o data-theme.
  await option(page, 'Maestro').click()
  await expect(page.locator('html')).not.toHaveAttribute('data-theme', /.+/)
  expect(await background(page)).toBe('rgb(11, 11, 12)')
})

test('um tema salvo que não existe mais abre o Maestro, sem erro', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('maestro:theme', 'tema-removido'))
  await page.goto('/preferencias')
  await expect(page.getByRole('heading', { name: 'Preferências', level: 1 })).toBeVisible()
  await expect(page.locator('html')).not.toHaveAttribute('data-theme', /.+/)
  expect(await background(page)).toBe('rgb(11, 11, 12)')
  await expect(option(page, 'Maestro').locator('input')).toBeChecked()
})
