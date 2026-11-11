import { execFileSync } from 'node:child_process'
import { writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { expect, test } from './fixtures'

test('diff distingue index e trabalho e acompanha preparar/despreparar', async ({ page, request }) => {
  const response = await request.get('/api/projects', { headers: { 'X-Maestro': '1' } })
  const projects = await response.json() as { name: string; path: string }[]
  const path = projects.find((p) => p.name === 'Alterações Demo')!.path
  const name = 'e2e-diff-scopes.txt'
  const git = (...args: string[]) => execFileSync('git', ['-C', path, '-c', 'user.name=E2E', '-c', 'user.email=e2e@example.com', ...args])
  writeFileSync(join(path, name), 'original\nsegunda\n')
  git('add', '--', name)
  git('commit', '-qm', 'Criar arquivo de teste de escopo', '--only', '--', name)
  writeFileSync(join(path, name), 'preparado\nsegunda\n')
  git('add', '--', name)
  writeFileSync(join(path, name), 'preparado\ntrabalho\n')
  try {
    await page.goto('/inbox')
    const nav = page.getByRole('navigation', { name: 'Navegação' })
    await nav.getByRole('button', { name: /sem conversa aberta/ }).click()
    await nav.getByRole('link', { name: /Alterações Demo/ }).first().click()
    await page.getByRole('tab', { name: /^Git/ }).click()
    const repo = page.getByTestId('scm-repo').first()
    const staged = repo.locator('[data-test="scm-group"][data-group="staged"]')
    const changes = repo.locator('[data-test="scm-group"][data-group="changes"]')
    const row = (group: typeof repo) => group.locator(`[data-test="scm-file"][data-path="${name}"]`)
    const dialog = page.getByRole('dialog')
    await row(staged).getByTestId('file-open').click()
    await expect(dialog.locator('[data-test="diff-line"][data-kind="add"]')).toContainText(['preparado'])
    await expect(dialog).not.toContainText('trabalho')
    await page.keyboard.press('Escape')
    await row(changes).getByTestId('file-open').click()
    await expect(dialog.locator('[data-test="diff-line"][data-kind="add"]')).toContainText(['trabalho'])
    await page.keyboard.press('Escape')
    await row(changes).hover()
    await row(changes).getByTestId('file-stage').click()
    await expect(row(changes)).toHaveCount(0)
    await row(staged).getByTestId('file-open').click()
    await expect(dialog).toContainText('trabalho')
    await page.keyboard.press('Escape')
    await row(staged).hover()
    await row(staged).getByTestId('file-unstage').click()
    await expect(row(staged)).toHaveCount(0)
    await row(changes).getByTestId('file-open').click()
    await expect(dialog).toContainText('preparado')
    await expect(dialog).toContainText('trabalho')
    await page.keyboard.press('Escape')
  } finally {
    git('rm', '-qf', '--', name)
    git('commit', '-qm', 'Remover arquivo de teste de escopo', '--only', '--', name)
  }
})
