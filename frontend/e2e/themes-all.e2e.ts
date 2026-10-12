import { expect, test } from './fixtures'

const THEMES = [
  { id: 'maestro', label: 'Maestro', background: 'rgb(11, 11, 12)' },
  { id: 'dracula', label: 'Dracula', background: 'rgb(33, 34, 44)' },
  { id: 'monokai-pro', label: 'Monokai Pro', background: 'rgb(34, 31, 34)' },
  { id: 'monokai-machine', label: 'Monokai Machine', background: 'rgb(29, 37, 40)' },
  { id: 'monokai-octagon', label: 'Monokai Octagon', background: 'rgb(30, 31, 43)' },
  { id: 'monokai-ristretto', label: 'Monokai Ristretto', background: 'rgb(33, 28, 28)' },
  { id: 'monokai-spectrum', label: 'Monokai Spectrum', background: 'rgb(25, 25, 25)' },
  { id: 'monokai-classic', label: 'Monokai Classic', background: 'rgb(29, 30, 25)' },
]

for (const theme of THEMES) {
  test(`o tema ${theme.label} muda o fundo, marca o cartão e vale em outras telas`, async ({ page }) => {
    await page.goto('/preferencias')
    const option = page.locator('[data-test="theme-option"]', { hasText: theme.label })
    await option.click()
    await expect(option.locator('input')).toBeChecked()
    await expect(page.locator('body')).toHaveCSS('background-color', theme.background)
    if (theme.id === 'maestro') await expect(page.locator('html')).not.toHaveAttribute('data-theme', /.+/)
    else await expect(page.locator('html')).toHaveAttribute('data-theme', theme.id)

    // A navegação dentro do app mantém o tema.
    await page.getByRole('link', { name: 'Dashboard' }).click()
    await expect(page).toHaveURL(/\/dashboard/)
    await expect(page.locator('body')).toHaveCSS('background-color', theme.background)
  })
}

test('a prévia de sessão segue o cartão sob o mouse e volta ao tema ativo', async ({ page }) => {
  await page.goto('/preferencias')
  const preview = page.locator('[data-test="theme-preview"]')
  await expect(preview).toHaveAttribute('data-theme', 'maestro')
  await page.locator('[data-test="theme-option"]', { hasText: 'Dracula' }).hover()
  await expect(preview).toHaveAttribute('data-theme', 'dracula')
  await expect(preview).toHaveCSS('background-color', 'rgb(33, 34, 44)')
  // Só a prévia mudou: o app continua no tema ativo.
  await expect(page.locator('html')).not.toHaveAttribute('data-theme', /.+/)
  await page.mouse.move(0, 0)
  await expect(preview).toHaveAttribute('data-theme', 'maestro')
})

test('cada cartão é pintado com o próprio tema', async ({ page }) => {
  await page.goto('/preferencias')
  const panel = (name: string) =>
    page.locator('[data-test="theme-option"]', { hasText: name }).evaluate((el) => getComputedStyle(el).backgroundColor)
  expect(await panel('Maestro')).toBe('rgb(25, 25, 28)')
  expect(await panel('Dracula')).toBe('rgb(40, 42, 54)')
  expect(await panel('Monokai Pro')).toBe('rgb(45, 42, 46)')
})

test('o tema troca pelo teclado, com as setas', async ({ page }) => {
  await page.goto('/preferencias')
  const maestro = page.locator('[data-test="theme-option"]', { hasText: 'Maestro' }).locator('input')
  await maestro.focus()
  await page.keyboard.press('ArrowRight')
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dracula')
  await page.keyboard.press('ArrowRight')
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'monokai-pro')
  await page.keyboard.press('ArrowLeft')
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dracula')
  await expect(page.locator('[data-test="theme-option"]', { hasText: 'Dracula' }).locator('input')).toBeChecked()
})
