import { expect, test } from './fixtures'

async function openProject(page: import('@playwright/test').Page) {
  await page.goto('/inbox')
  const nav = page.getByRole('navigation', { name: 'Navegação' })
  // The project has no conversation, so the sidebar keeps it under "Outros projetos".
  await nav.getByRole('button', { name: /sem conversa aberta/ }).click()
  await nav.getByRole('link', { name: /Alterações Demo/ }).first().click()
  const repo = page.getByTestId('scm-repo').first()
  await expect(repo).toBeVisible()
  return repo
}

test('preparar, commitar e descartar', async ({ page }) => {
  const repo = await openProject(page)
  const changes = repo.locator('[data-test="scm-group"][data-group="changes"]')
  await expect(changes.getByTestId('scm-group-count')).toHaveText('3')

  await repo.locator('[data-test="scm-file"][data-path="src/carrinho.ts"]').hover()
  await repo.locator('[data-test="scm-file"][data-path="src/carrinho.ts"] [data-test="file-stage"]').click()
  const staged = repo.locator('[data-test="scm-group"][data-group="staged"]')
  await expect(staged.getByTestId('scm-group-count')).toHaveText('1')
  await expect(repo.getByTestId('primary-action')).toHaveText('Commitar 1 preparado')

  await repo.getByTestId('commit-message').fill('Somar o frete no carrinho')
  await repo.getByTestId('commit-message').press('Control+Enter')
  await expect(staged).toHaveCount(0)
  await expect(changes.getByTestId('scm-group-count')).toHaveText('2')
  await expect(repo.getByTestId('commit-message')).toHaveValue('')

  const cupom = repo.locator('[data-test="scm-file"][data-path="src/cupom.ts"]')
  await cupom.hover()
  await cupom.getByTestId('file-discard').click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toContainText('descartar apaga o arquivo')
  await dialog.getByTestId('confirm-ok').click()
  await expect(cupom).toHaveCount(0)

  await repo.locator('[data-test="scm-file"][data-path="README.md"] [data-test="file-open"]').click()
  await expect(repo.locator('[data-test="diff-line"][data-kind="add"]').first()).toBeVisible()

  const commits = page.getByTestId('commits-section').getByTestId('commits-repo').first()
  await commits.getByTestId('commits-repo-toggle').click()
  await expect(commits.getByTestId('commit-row').filter({ hasText: 'Somar o frete no carrinho' })).toHaveCount(1)
})
