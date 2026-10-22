import { expect, test } from './fixtures'

// "Ramos Demo" (scripts/e2e_server.py) has three repositories (api, docs, web) and one conversation.
const TITLE = 'Confira os ramos dos repositórios'

test('Detalhes mostra só o primeiro repositório e expande e recolhe os demais', async ({ page }) => {
  await page.goto('/sessions')
  await page.getByTestId('row-link').filter({ hasText: TITLE }).first().click()
  await expect(page).toHaveURL(/\/sessions\/[0-9a-f-]+/)
  const branch = page.getByTestId('prop-branch')
  if (!(await branch.isVisible())) await page.getByTestId('toggle-details').first().click()
  await expect(branch).toBeVisible()

  const toggle = page.getByTestId('prop-branch-toggle')
  await expect(branch).toContainText('api')
  await expect(branch).not.toContainText('docs')
  await expect(branch).not.toContainText('web')
  await expect(toggle).toHaveText('+ 2 repositórios')
  await expect(toggle).toHaveAttribute('aria-expanded', 'false')
  await expect(page.getByTestId('prop-branch-more')).toHaveCount(0)

  await toggle.click()
  await expect(toggle).toHaveText('menos')
  await expect(toggle).toHaveAttribute('aria-expanded', 'true')
  const more = page.getByTestId('prop-branch-more')
  await expect(more).toContainText('docs')
  await expect(more).toContainText('web')
  await expect(branch).toContainText('api')

  // The toggle works from the keyboard and folds the list again.
  await toggle.focus()
  await page.keyboard.press('Enter')
  await expect(toggle).toHaveAttribute('aria-expanded', 'false')
  await expect(toggle).toHaveText('+ 2 repositórios')
  await expect(page.getByTestId('prop-branch-more')).toHaveCount(0)
})

test('a lista volta recolhida ao trocar de conversa e voltar', async ({ page }) => {
  await page.goto('/sessions')
  await page.getByTestId('row-link').filter({ hasText: TITLE }).first().click()
  const branch = page.getByTestId('prop-branch')
  if (!(await branch.isVisible())) await page.getByTestId('toggle-details').first().click()
  const toggle = page.getByTestId('prop-branch-toggle')
  await toggle.click()
  await expect(toggle).toHaveAttribute('aria-expanded', 'true')

  // Another project's conversation, then back to this one.
  await page.goto('/sessions')
  await page.getByTestId('row-link').filter({ hasText: 'Liste as tarefas pendentes' }).first().click()
  await expect(page.getByTestId('prop-branch-toggle')).toHaveCount(0)
  await page.goto('/sessions')
  await page.getByTestId('row-link').filter({ hasText: TITLE }).first().click()
  if (!(await branch.isVisible())) await page.getByTestId('toggle-details').first().click()
  await expect(page.getByTestId('prop-branch-toggle')).toHaveAttribute('aria-expanded', 'false')
  await expect(page.getByTestId('prop-branch-more')).toHaveCount(0)
})
