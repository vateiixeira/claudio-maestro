import { expect, test } from './fixtures'

test('busca projetos e abre ações secundárias por teclado', async ({ page }) => {
  await page.goto('/projects')
  // The conversations load after the page: until they do every project sits in "Parados" and rows jump groups.
  await expect(page.locator('[data-test="project-group"][data-group="active"]')).toBeVisible()
  const search = page.getByTestId('project-search')
  await expect(search).toBeVisible()
  await search.fill('Loja Demo')
  await expect(page.getByTestId('project-row')).toHaveCount(1)
  const row = page.getByTestId('project-row')
  const rename = page.getByRole('menuitem', { name: 'Renomear', exact: true })
  await expect(rename).toHaveCount(0)
  await row.getByTestId('project-actions').focus()
  await page.keyboard.press('Enter')
  await expect(rename).toBeVisible()
  await expect(rename).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(row.getByTestId('project-actions')).toBeFocused()
  await expect(rename).toHaveCount(0)
  await search.fill('projeto-inexistente-427')
  await expect(page.getByText('Nenhum projeto encontrado.', { exact: false })).toBeVisible()
  await search.fill('')
  await expect(page.getByTestId('project-row').first()).toBeVisible()
})

test('estado vazio de tarefas leva à organização do projeto escolhido', async ({ page }) => {
  await page.route('**/api/tasks?*', route => route.fulfill({ json: [] }))
  await page.goto('/tarefas')
  const empty = page.getByTestId('tasks-empty')
  await expect(empty).toBeVisible()
  // "Onde criar" lists the projects that have an organization, each with its link.
  await expect(empty.getByTestId('tasks-where-project')).toHaveCount(1)
  await empty.getByTestId('tasks-where-project').filter({ hasText: 'Loja Demo' }).getByTestId('tasks-open-organization').click()
  await expect(page.getByTestId('project-tab-organizacao')).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByTestId('org-tree')).toBeVisible()
})
