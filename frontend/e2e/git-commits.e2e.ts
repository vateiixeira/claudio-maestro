import { expect, test } from './fixtures'

test('histórico de commits: grupos, abrir commit, carregar mais e escolher branch', async ({ page }) => {
  await page.goto('/inbox')
  const nav = page.getByRole('navigation', { name: 'Navegação' })
  // The project has no conversation, so the sidebar keeps it under "Outros projetos".
  await nav.getByRole('button', { name: /sem conversa aberta/ }).click()
  await nav.getByRole('link', { name: /Histórico Demo/ }).first().click()
  const section = page.getByTestId('commits-section')
  await expect(section).toBeVisible()
  const api = section.getByTestId('commits-repo').filter({ hasText: 'api' })
  await expect(api.getByTestId('sync-counts')).toHaveAttribute('aria-label', '1 para baixar, 2 para subir')

  await api.getByTestId('commits-repo-toggle').click()
  await expect(api.getByTestId('group-outgoing')).toContainText('Para subir — 2 commits')
  await expect(api.getByTestId('group-incoming')).toContainText('Para baixar — 1 commit')
  await expect(api.getByTestId('commit-row')).toHaveCount(30)

  await api.getByTestId('load-more').click()
  await expect(api.getByTestId('commit-row')).toHaveCount(35)
  await expect(api.getByTestId('load-more')).toHaveCount(0)

  await api.getByTestId('group-incoming').getByRole('button').click()
  await expect(api.getByTestId('incoming-list')).toContainText('Corrigir o cabeçalho no remoto')
  // The branch is behind, so the upstream's tip is among the commits to pull.
  await expect(api.getByTestId('incoming-list').getByTestId('upstream-tag')).toHaveText('origin')

  const first = api.getByTestId('commit-row').filter({ hasText: 'Ajustar a rota 35' })
  await first.getByTestId('commit-toggle').click()
  await expect(first.getByTestId('commit-file')).toContainText('rota35.txt')
  await first.getByTestId('commit-file').getByRole('button').click()
  await expect(first.locator('[data-test="diff-line"][data-kind="add"]')).toContainText('Ajustar a rota 35')

  await api.getByTestId('history-ref').click()
  await page.getByRole('option', { name: 'feat/relatorios' }).click()
  await expect(api.getByTestId('history-ref')).toHaveText('feat/relatorios')
  await expect(api.getByTestId('commit-row').first()).toContainText('Criar o relatório de vendas')
})

test('histórico de commits: copiar hash e mensagem e recarregar ao reabrir', async ({ page, context }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write'])
  await page.goto('/inbox')
  const nav = page.getByRole('navigation', { name: 'Navegação' })
  await nav.getByRole('button', { name: /sem conversa aberta/ }).click()
  await nav.getByRole('link', { name: /Histórico Demo/ }).first().click()
  const web = page.getByTestId('commits-section').getByTestId('commits-repo').filter({ hasText: 'web' })
  const toggle = web.getByTestId('commits-repo-toggle')

  await toggle.click()
  const row = web.getByTestId('commit-row').filter({ hasText: 'Montar a página 3' })
  await row.getByTestId('commit-toggle').click()
  await row.getByTestId('copy-message').click()
  await expect(row.getByTestId('copy-message')).toHaveText('Copiado')
  expect(await page.evaluate(() => navigator.clipboard.readText())).toContain('Montar a página 3')
  await row.getByTestId('copy-hash').click()
  await expect(row.getByTestId('copy-hash')).toHaveAttribute('aria-label', 'Hash copiado')
  expect(await page.evaluate(() => navigator.clipboard.readText())).toMatch(/^[0-9a-f]{40}$/)

  // Closing and reopening the block asks for the history again.
  await toggle.click()
  const reload = page.waitForRequest((request) => request.url().includes('/git/log'))
  await toggle.click()
  await reload
  await expect(web.getByTestId('commit-row').first()).toContainText('Montar a página 3')
})
