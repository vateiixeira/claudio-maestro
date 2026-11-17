import { expect, test } from './fixtures'

test('abrir projetos pelo menu e renomear o cadastro sem mudar a pasta', async ({ page }, testInfo) => {
  await page.goto('/inicio')
  await page.getByTestId('nav-projects').click()
  await expect(page).toHaveURL(/\/projects$/)
  await expect(page.getByRole('heading', { name: 'Projetos', exact: true })).toBeVisible()
  await expect(page.getByTestId('nav-projects')).toHaveAttribute('aria-current', 'page')
  // The conversations load after the page: until they do every project sits in "Parados" and rows jump groups.
  await expect(page.locator('[data-test="project-group"][data-group="active"]')).toBeVisible()
  const row = page.getByTestId('project-row').filter({ has: page.getByRole('link', { name: 'Loja Demo', exact: true }) })
  const path = await row.getByTestId('project-path').innerText()
  const stableRow = page.getByTestId('project-row').filter({ has: page.getByTestId('project-path').filter({ hasText: path }) })
  await row.getByTestId('project-actions').click()
  await page.getByRole('menuitem', { name: 'Renomear', exact: true }).click()
  await row.getByRole('textbox', { name: 'Nome do projeto' }).fill('Loja personalizada')
  await row.getByRole('button', { name: 'Salvar', exact: true }).click()
  await expect(stableRow.getByRole('link', { name: 'Loja personalizada', exact: true })).toBeVisible()
  await expect(stableRow.getByTestId('project-path')).toHaveText(path)
  await page.screenshot({ path: testInfo.outputPath('projetos-desktop.png'), fullPage: true })
  await page.reload()
  await expect(page.locator('[data-test="project-group"][data-group="active"]')).toBeVisible()
  const renamed = page.getByTestId('project-row').filter({ has: page.getByRole('link', { name: 'Loja personalizada', exact: true }) })
  await expect(renamed.getByTestId('project-path')).toHaveText(path)
  await renamed.getByTestId('project-actions').click()
  await page.getByRole('menuitem', { name: 'Renomear', exact: true }).click()
  await renamed.getByRole('textbox', { name: 'Nome do projeto' }).fill('Loja Demo')
  await renamed.getByRole('button', { name: 'Salvar', exact: true }).click()
  await expect(page.getByRole('main').getByRole('link', { name: 'Loja Demo', exact: true })).toBeVisible()
})


test('lista de projetos e navegação cabem no celular', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/projects')
  await expect(page.getByRole('heading', { name: 'Projetos', exact: true })).toBeVisible()
  await expect(page.getByTestId('project-row').first()).toBeVisible()
  // The conversations load after the page: until they do every project sits in "Parados" and rows jump groups.
  await expect(page.locator('[data-test="project-group"][data-group="active"]')).toBeVisible()
  await page.getByRole('button', { name: 'Abrir navegação', exact: true }).click()
  await expect(page.getByTestId('nav-projects')).toBeVisible()
  await page.getByRole('button', { name: 'Fechar navegação', exact: true }).click({ position: { x: 380, y: 400 } })
  const row = page.getByTestId('project-row').first()
  await row.getByTestId('project-actions').click()
  await page.getByTestId('more-menu-item').and(page.locator('[data-id="rename"]')).click()
  await expect(row.getByRole('textbox', { name: 'Nome do projeto' })).toBeFocused()
  await expect(row.getByRole('button', { name: 'Salvar', exact: true })).toBeInViewport()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.screenshot({ path: testInfo.outputPath('projetos-celular.png'), fullPage: true })
  await row.getByRole('button', { name: 'Cancelar', exact: true }).click()
})

test('a tabela agrupa os projetos por atividade e mostra conversas e tempo de cada um', async ({ page }) => {
  await page.goto('/projects')
  // The conversations load after the page: until they do every project sits in "Parados" and rows jump groups.
  await expect(page.locator('[data-test="project-group"][data-group="active"]')).toBeVisible()
  const table = page.getByRole('table', { name: 'Projetos cadastrados' })
  for (const name of ['Projeto', 'Branch', 'Conversas', 'Alterações', 'Atividade']) {
    await expect(table.getByRole('columnheader', { name, exact: true })).toBeVisible()
  }
  const active = page.locator('[data-test="project-group"][data-group="active"]')
  const idle = page.locator('[data-test="project-group"][data-group="idle"]')
  // Open conversations put a project in "Ativos hoje", whatever the clock says.
  const loja = active.getByTestId('project-row').filter({ has: page.getByRole('link', { name: 'Loja Demo', exact: true }) })
  await expect(loja).toHaveCount(1)
  await expect(loja.getByTestId('project-conversations')).toHaveText(/\d+ abertas?/)
  await expect(loja.getByTestId('project-activity')).toHaveText(/^há /)
  await expect(active.getByRole('link', { name: 'Painel Demo', exact: true })).toBeVisible()
  // A project with no conversation at all sits in "Parados" with "sem uso" in the time column.
  await expect(idle.getByTestId('project-row').first()).toBeVisible()
  await expect(idle.getByTestId('project-activity').first()).toHaveText('sem uso')
  // The rename lives in the "more" menu; the row has no other action button.
  await loja.getByTestId('project-actions').click()
  await expect(page.getByRole('menu')).toBeVisible()
  await expect(page.getByTestId('more-menu-item')).toHaveText(['Renomear'])
  // The panel sits right under its button, aligned to the button's right edge, inside the window.
  const button = (await loja.getByTestId('project-actions').boundingBox())!
  const panel = (await page.getByRole('menu').boundingBox())!
  expect(Math.abs(panel.x + panel.width - (button.x + button.width)), 'alinhado à direita do botão').toBeLessThanOrEqual(1)
  expect(panel.y - (button.y + button.height), 'logo abaixo do botão').toBeLessThanOrEqual(8)
  expect(panel.y).toBeGreaterThanOrEqual(button.y + button.height)
  await page.keyboard.press('Escape')
  await expect(page.getByRole('menu')).toHaveCount(0)
})
