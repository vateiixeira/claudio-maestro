import { expect, openSeededSession, test } from './fixtures'

test.describe('imagens dos resultados de ferramenta', () => {
  test.beforeEach(async ({ page }) => {
    await openSeededSession(page, 'Conversa com imagens')
  })

  test('mostra a faixa com as quatro miniaturas com o bloco fechado', async ({ page }) => {
    const strip = page.getByTestId('tool-image-strip')
    await expect(strip).toBeVisible()
    await expect(page.getByTestId('tool-image-count')).toHaveText('4 imagens')
    await expect(page.getByTestId('tool-image')).toHaveCount(4)
    for (const n of [1, 2, 3, 4]) {
      await expect(page.getByRole('button', { name: `Abrir imagem ${n} de 4` })).toBeVisible()
    }
    // Every thumbnail finished loading its bytes.
    await expect.poll(() => strip.locator('img').evaluateAll((imgs) => imgs.filter((i) => (i as HTMLImageElement).naturalWidth > 0).length)).toBe(4)
    await expect(page.getByText('[Imagem omitida]')).toHaveCount(0)
    await expect(page.getByText('Imagem indisponível')).toHaveCount(0)
  })

  test('abre na segunda imagem e navega por setas da tela e pelo teclado, parando nas pontas', async ({ page }) => {
    await page.getByRole('button', { name: 'Abrir imagem 2 de 4' }).click()
    const viewer = page.getByRole('dialog')
    await expect(viewer).toBeVisible()
    const counter = page.getByTestId('image-viewer-counter')
    const caption = page.getByTestId('image-viewer-caption')
    const prev = page.getByRole('button', { name: 'Imagem anterior' })
    const next = page.getByRole('button', { name: 'Próxima imagem' })

    await expect(counter).toHaveText('2 de 4')
    await expect(caption).toHaveText('Read · tela.png')
    await expect(page.getByTestId('image-viewer-image')).toBeVisible()
    await expect(page.getByText('[Imagem omitida]')).toHaveCount(0)

    await prev.click()
    await expect(counter).toHaveText('1 de 4')
    await expect(prev).toBeDisabled()
    await page.keyboard.press('ArrowLeft')
    await expect(counter).toHaveText('1 de 4')

    await page.keyboard.press('ArrowRight')
    await page.keyboard.press('ArrowRight')
    await expect(counter).toHaveText('3 de 4')
    await expect(caption).toHaveText('Read · tela.png')
    await next.click()
    await expect(counter).toHaveText('4 de 4')
    await expect(caption).toContainText('browser_take_screenshot')
    await expect(next).toBeDisabled()
    await page.keyboard.press('ArrowRight')
    await expect(counter).toHaveText('4 de 4')
    await expect(page.getByTestId('image-viewer-image')).toBeVisible()
  })

  test('Esc e o botão de fechar fecham o visualizador e devolvem o foco à miniatura', async ({ page }) => {
    const thumb = page.getByRole('button', { name: 'Abrir imagem 3 de 4' })
    await thumb.click()
    await expect(page.getByRole('dialog')).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await expect(thumb).toBeFocused()

    await thumb.click()
    await expect(page.getByRole('dialog')).toBeVisible()
    await page.getByRole('button', { name: 'Fechar imagem' }).click()
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await expect(thumb).toBeFocused()
  })

  test('abrir o bloco não repete a faixa dentro da linha do Read', async ({ page }) => {
    await page.getByRole('button', { name: /Leu tela\.png/ }).click()
    await expect(page.getByTestId('tool-image-strip')).toHaveCount(1)
    await expect(page.getByTestId('tool-image')).toHaveCount(4)
    await expect(page.getByText('[Imagem omitida]')).toHaveCount(0)
  })

  test('numa tela estreita a página não rola na horizontal e o visualizador cabe na tela', async ({ page }) => {
    await expect(page.getByTestId('tool-image')).toHaveCount(4)
    await page.getByRole('button', { name: 'Abrir imagem 1 de 4' }).click()
    await expect(page.getByRole('dialog')).toBeVisible()
    await page.setViewportSize({ width: 375, height: 700 })
    const box = await page.getByRole('dialog').boundingBox()
    expect(box!.x).toBeGreaterThanOrEqual(0)
    expect(box!.x + box!.width).toBeLessThanOrEqual(375)
    await expect(page.getByTestId('image-viewer-image')).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(page.getByRole('dialog')).toHaveCount(0)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  })
})
