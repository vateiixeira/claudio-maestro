import { expect, test, openNavigationGroup } from './fixtures'

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
    await openNavigationGroup(page, 'Mais ferramentas')
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

for (const label of ['Monokai Ristretto', 'Monokai Spectrum']) {
  test(`o nome ${label} aparece inteiro no cartão ativo`, async ({ page }) => {
    // Viewport estreito: os cartões ficam na largura mínima da grade, o pior caso para o nome.
    await page.setViewportSize({ width: 560, height: 800 })
    await page.goto('/preferencias')
    const option = page.locator('[data-test="theme-option"]', { hasText: label })
    await option.click()
    await expect(option.locator('input')).toBeChecked()
    const name = option.locator('[data-test="theme-name"]')
    await expect(name).toHaveText(label)
    const { scrollWidth, clientWidth } = await name.evaluate((el) => ({
      scrollWidth: el.scrollWidth,
      clientWidth: el.clientWidth,
    }))
    expect(scrollWidth).toBeLessThanOrEqual(clientWidth)
  })
}

const THEME_IDS = THEMES.map((t) => t.id)
const card = (page: import('@playwright/test').Page, id: string) =>
  page.locator(`[data-test="theme-option"][data-theme="${id}"]`)

test('a marca Ativo aparece só no cartão do tema ativo e os cartões são distintos', async ({ page }) => {
  await page.goto('/preferencias')
  for (const id of ['dracula', 'monokai-classic', 'maestro']) {
    await card(page, id).click()
    await expect(page.locator('[data-test="theme-active"]')).toHaveCount(1)
    await expect(card(page, id).locator('[data-test="theme-active"]')).toHaveText('Ativo')
  }
  const looks = await page.locator('[data-test="theme-option"]').evaluateAll((els) =>
    els.map((el) => {
      const code = el.querySelector('span[style]') as HTMLElement
      return `${getComputedStyle(el).backgroundColor}|${getComputedStyle(code).color}`
    }),
  )
  expect(new Set(looks).size).toBe(THEME_IDS.length)
})

test('os nomes dos cartões não são cortados nem quebram em 1100 px', async ({ page }) => {
  await page.setViewportSize({ width: 1100, height: 800 })
  await page.goto('/preferencias')
  const names = await page.locator('[data-test="theme-name"]').evaluateAll((els) =>
    els.map((el) => {
      const range = document.createRange()
      range.selectNodeContents(el)
      return { truncated: el.scrollWidth > el.clientWidth, lines: range.getClientRects().length }
    }),
  )
  expect(names).toHaveLength(THEME_IDS.length)
  for (const n of names) expect(n).toEqual({ truncated: false, lines: 1 })
})

test('a prévia segue o foco do teclado, fica inerte e a legenda é lida', async ({ page }) => {
  await page.goto('/preferencias')
  const preview = page.locator('[data-test="theme-preview"]')
  await card(page, 'maestro').locator('input').focus()
  await page.keyboard.press('ArrowRight')
  await expect(preview).toHaveAttribute('data-theme', 'dracula')
  await expect(page.locator('[data-test="theme-preview-caption"]')).toHaveText('Prévia: Dracula')
  await expect(preview).toHaveAttribute('aria-hidden', 'true')
  await expect(preview).toHaveAttribute('inert', '')
  // O foco do teclado não entra na prévia: o link e os botões dela são só desenho.
  await expect(page.getByText('Prévia: Dracula')).toBeVisible()
  expect(await preview.evaluate((el) => el.contains(document.activeElement))).toBe(false)
  // Depois de escolher, a prévia mostra o novo ativo.
  await page.mouse.move(0, 0)
  await expect(preview).toHaveAttribute('data-theme', 'dracula')
})

test('nenhuma cor do tema ativo vaza para dentro da prévia de outro tema', async ({ page }) => {
  await page.goto('/preferencias')
  const preview = page.locator('[data-test="theme-preview"]')
  const signature = () =>
    preview.evaluate((root) =>
      [root, ...root.querySelectorAll('*')].map((el) => {
        const s = getComputedStyle(el)
        return [s.color, s.backgroundColor, s.borderTopColor, s.borderBottomColor, s.fill, s.stroke].join('|')
      }),
    )
  // Referência: a prévia do Maestro com o Maestro ativo.
  await card(page, 'maestro').hover()
  const reference = await signature()
  await card(page, 'dracula').click()
  await card(page, 'maestro').hover()
  await expect(preview).toHaveAttribute('data-theme', 'maestro')
  expect(await signature()).toEqual(reference)
  // E o inverso: a prévia do Dracula é a mesma com o Maestro ativo.
  await card(page, 'dracula').hover()
  const dracula = await signature()
  await card(page, 'maestro').click()
  await card(page, 'dracula').hover()
  await expect(preview).toHaveAttribute('data-theme', 'dracula')
  expect(await signature()).toEqual(dracula)
})
