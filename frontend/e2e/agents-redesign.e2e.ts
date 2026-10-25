import { expect, test } from './fixtures'

for (const width of [1920, 1440, 1280, 1024, 768, 430, 375]) {
  test(`página do agente mantém hierarquia e controles utilizáveis em ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await page.goto('/agentes/1')
    await expect(page.getByTestId('agent-name')).toHaveText('Triagem')
    await expect(page.getByTestId('agent-picker-toggle')).toContainText('Triagem')
    for (const tab of ['conversations', 'runs', 'settings']) {
      await page.getByTestId(`agent-tab-${tab}`).click()
      await expect(page.getByTestId(`agent-tab-${tab}`)).toHaveAttribute('aria-selected', 'true')
      const layout = await page.evaluate(() => ({
        viewport: innerWidth,
        page: document.documentElement.scrollWidth,
        content: document.querySelector('[aria-label="Detalhe do agente"]')!.getBoundingClientRect().width,
      }))
      expect(layout.page).toBeLessThanOrEqual(layout.viewport + 1)
      expect(layout.content).toBeGreaterThanOrEqual(Math.min(width, 600) - 2)
      await page.screenshot({ path: `/tmp/maestro-redesign-agentes/${width}-${tab}.png`, fullPage: true })
    }
    if (width < 1024) {
      const toggle = page.getByTestId('agents-mobile-menu')
      await expect(toggle).toBeVisible()
      await toggle.click()
      await expect(page.getByRole('dialog', { name: 'Navegação' })).toBeVisible()
      await page.keyboard.press('Escape')
      await expect(page.getByRole('dialog', { name: 'Navegação' })).toHaveCount(0)
      await expect(toggle).toBeFocused()
    }
  })
}

test('atalhos da configuração levam aos grupos e a edição sobrevive à troca de seção', async ({ page }) => {
  await page.goto('/agentes/1?aba=settings')
  await page.getByTestId('skill-text').fill('Rascunho local que ainda não deve ser salvo')
  await page.getByTestId('agent-tab-conversations').click()
  await page.getByTestId('agent-tab-settings').click()
  await expect(page.getByTestId('skill-text')).toHaveValue('Rascunho local que ainda não deve ser salvo')
  await page.getByRole('navigation', { name: 'Navegar pela configuração' }).getByRole('link', { name: 'Memória' }).click()
  await expect(page.getByTestId('learnings-text')).toBeInViewport()
})

test('a atividade filtra problemas sem perder o acesso ao histórico completo', async ({ page }) => {
  await page.goto('/agentes/1?aba=runs')
  await expect(page.getByTestId('run-row')).toHaveCount(2)
  await page.getByTestId('run-filter-problems').click()
  await expect(page.getByTestId('run-row')).toHaveCount(1)
  await expect(page.getByTestId('run-row')).toContainText('O token do repositório expirou.')
  await page.getByTestId('run-filter-all').click()
  await expect(page.getByTestId('run-row')).toHaveCount(2)
})
