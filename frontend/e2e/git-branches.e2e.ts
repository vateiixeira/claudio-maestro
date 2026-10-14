import { expect, test } from './fixtures'

// The three tests change the same repository of "Merge Demo" and run in order.
test.describe.configure({ mode: 'serial' })

async function openRepo(page: import('@playwright/test').Page) {
  await page.goto('/inbox')
  const nav = page.getByRole('navigation', { name: 'Navegação' })
  // The project has no conversation, so the sidebar keeps it under "Outros projetos".
  await nav.getByRole('button', { name: /sem conversa aberta/ }).click()
  await nav.getByRole('link', { name: /Merge Demo/ }).first().click()
  const repo = page.getByTestId('scm-repo').first()
  await expect(repo).toBeVisible()
  return repo
}

async function openCommits(page: import('@playwright/test').Page) {
  const commits = page.getByTestId('commits-section').getByTestId('commits-repo').first()
  if (await commits.getByTestId('commit-row').count() === 0) await commits.getByTestId('commits-repo-toggle').click()
  return commits
}

test('criar branch, trocar e mesclar sem conflito', async ({ page }) => {
  const repo = await openRepo(page)
  await repo.getByTestId('branch-chip').click()
  await page.getByTestId('branch-search').fill('fix frete')
  await expect(page.getByTestId('branch-create')).toBeVisible()
  await page.getByTestId('branch-create').click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByTestId('branch-error')).toHaveText('Nome de branch não pode ter espaço. Por exemplo: fix-frete.')
  await expect(dialog.getByTestId('confirm-ok')).toBeDisabled()
  await dialog.getByTestId('branch-name').fill('fix/frete')
  await dialog.getByTestId('branch-name').press('Enter')
  await expect(repo.getByTestId('branch-chip')).toHaveText('fix/frete')

  await repo.getByTestId('branch-chip').click()
  await page.getByTestId('branch-search').fill('main')
  await expect(page.locator('[data-test="branch-item"][data-name="main"]')).toBeVisible()
  await page.getByTestId('branch-search').press('ArrowDown')
  await page.getByTestId('branch-search').press('Enter')
  await expect(repo.getByTestId('branch-chip')).toHaveText('main')

  await repo.getByTestId('repo-merge').click()
  await page.locator('[data-test="branch-item"][data-name="feat/docs"]').click()
  await expect(page.getByRole('dialog')).toContainText('Entra 1 commit de feat/docs.')
  await page.getByRole('dialog').getByTestId('confirm-ok').click()
  await expect(repo.getByTestId('merge-banner')).toHaveCount(0)
  const commits = await openCommits(page)
  await expect(commits.getByTestId('commit-row').first()).toContainText("Merge branch 'feat/docs'")
})

test('merge com conflito mostra o bloco e aborta', async ({ page, consoleErrors }) => {
  const repo = await openRepo(page)
  await repo.getByTestId('repo-merge').click()
  await page.locator('[data-test="branch-item"][data-name="feat/cupom"]').click()
  await page.getByRole('dialog').getByTestId('confirm-ok').click()
  const banner = repo.getByTestId('merge-banner')
  await expect(banner).toContainText('O merge de feat/cupom em main parou em 1 arquivo com conflito.')
  await expect(repo.getByTestId('primary-action')).toHaveText('Concluir merge (falta resolver 1)')
  await expect(repo.getByTestId('primary-action')).toBeDisabled()
  const conflict = repo.locator('[data-test="scm-group"][data-group="conflict"]')
  await expect(conflict.getByTestId('file-stage')).toHaveCount(0)
  await expect(conflict.getByTestId('file-discard')).toHaveCount(0)
  await conflict.locator('[data-test="file-open"]').click()
  await expect(repo.locator('[data-marker="ours"]')).toContainText('main (sua branch)')
  await expect(repo.locator('[data-marker="theirs"]')).toContainText('feat/cupom (a que entra)')
  // While the merge is open the disabled icons say why.
  await expect(repo.getByTestId('repo-commit')).toHaveAttribute('title', 'Conclua o merge com Concluir merge')
  await expect(repo.getByTestId('repo-merge')).toHaveAttribute('title', 'Já há um merge em andamento')
  await expect(repo.getByTestId('branch-chip')).toHaveAttribute('title', 'Conclua ou aborte o merge antes de trocar de branch')
  // The API refuses to stage or discard a file in conflict, even though the screen does not offer it.
  const refusals = await page.evaluate(async (repoPath) => {
    const projectId = location.pathname.split('/')[2]
    const out: Array<{ status: number; message: string }> = []
    for (const action of ['stage', 'discard']) {
      const response = await fetch(`/api/projects/${projectId}/git/${action}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Maestro': '1' },
        body: JSON.stringify({ repo: repoPath, paths: ['src/frete.ts'] }),
      })
      const body = await response.json()
      out.push({ status: response.status, message: body.detail?.message ?? JSON.stringify(body) })
    }
    return out
  }, (await repo.getAttribute('data-repo')) as string)
  for (const refusal of refusals) {
    expect(refusal.status).toBeGreaterThanOrEqual(400)
    expect(refusal.message).toBe('Arquivo em conflito: resolva e use Marcar como resolvido.')
  }
  await expect(conflict.locator('[data-test="scm-file"]')).toHaveCount(1)
  // Resolving a file that still has the markers is refused, with the reason on screen.
  await conflict.locator('[data-test="scm-file"]').hover()
  await conflict.getByTestId('file-resolve').click()
  await expect(repo.getByRole('alert')).toContainText('ainda tem marcas de conflito')
  // The browser logs the refused request (400) as a console error: it is the expected one.
  expect(consoleErrors.filter((m) => !m.includes('400') && !m.includes('409'))).toEqual([])
  consoleErrors.length = 0
  await expect(banner).toBeVisible()
  // The branch button is off while the merge is open.
  await expect(repo.getByTestId('branch-chip')).toBeDisabled()
  // Cancelling the confirmation keeps the merge.
  await banner.getByTestId('merge-abort').click()
  await page.getByRole('dialog').getByTestId('confirm-cancel').click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(banner).toBeVisible()
  await banner.getByTestId('merge-abort').click()
  await page.getByRole('dialog').getByTestId('confirm-ok').click()
  await expect(banner).toHaveCount(0)
  await expect(repo.getByTestId('commit-message')).toHaveValue('')
  await expect(repo.locator('[data-test="scm-group"][data-group="conflict"]')).toHaveCount(0)
  await expect(repo.getByTestId('branch-chip')).toHaveText('main')
})

test('merge com conflito até concluir', async ({ page }) => {
  const repo = await openRepo(page)
  await repo.getByTestId('repo-merge').click()
  await page.locator('[data-test="branch-item"][data-name="feat/limpeza"]').click()
  await page.getByRole('dialog').getByTestId('confirm-ok').click()
  await expect(repo.getByTestId('merge-banner')).toContainText('parou em 1 arquivo com conflito')
  const row = repo.locator('[data-test="scm-group"][data-group="conflict"] [data-test="scm-file"][data-path="docs/antigo.md"]')
  await row.hover()
  await row.getByTestId('file-resolve').click()
  await expect(repo.getByTestId('merge-banner')).toContainText('Conflitos resolvidos')
  await expect(repo.getByTestId('commit-message')).toHaveValue("Merge branch 'feat/limpeza'")
  await repo.getByTestId('primary-action').click()
  await expect(repo.getByTestId('merge-banner')).toHaveCount(0)
  await expect(repo.getByTestId('commit-message')).toHaveValue('')
  const commits = await openCommits(page)
  await expect(commits.getByTestId('commit-row').first()).toContainText("Merge branch 'feat/limpeza'")
})

test('menu de branches: teclado, Esc, clique fora e foco fora', async ({ page }) => {
  const repo = await openRepo(page)
  const chip = repo.getByTestId('branch-chip')
  const search = page.getByTestId('branch-search')
  const menu = page.getByTestId('branch-menu')

  await chip.click()
  await expect(search).toBeFocused()
  await expect(menu.locator('[data-test="branch-item"][data-name="main"]')).toContainText('atual')
  await expect(menu.getByRole('option').first()).toHaveAttribute('aria-selected', 'true')
  await search.press('ArrowDown')
  await expect(menu.getByRole('option').nth(1)).toHaveAttribute('aria-selected', 'true')
  await search.press('ArrowUp')
  await expect(menu.getByRole('option').first()).toHaveAttribute('aria-selected', 'true')
  await search.fill('feat/')
  await expect(menu.getByTestId('branch-item').first()).toContainText('feat/')
  await search.fill('zzz-nada')
  await expect(menu.getByTestId('branch-item')).toHaveCount(0)

  // Esc closes and the focus goes back to the branch button.
  await search.press('Escape')
  await expect(menu).toHaveCount(0)
  await expect(chip).toBeFocused()

  // Click outside closes.
  await chip.click()
  await expect(menu).toBeVisible()
  await page.mouse.click(600, 600)
  await expect(menu).toHaveCount(0)

  // The focus leaving the menu closes it.
  await chip.click()
  await expect(search).toBeFocused()
  await search.press('Tab')
  await expect(menu).toHaveCount(0)

  // Esc in the merge menu too, and the branch stays main.
  await repo.getByTestId('repo-merge').click()
  await expect(page.getByTestId('branch-search')).toBeFocused()
  await expect(page.locator('[data-test="branch-item"][data-name="main"]')).toHaveCount(0)
  await page.getByTestId('branch-search').press('Escape')
  await expect(menu).toHaveCount(0)
  await expect(chip).toHaveText('main')
})

test('criar branch: o erro do servidor aparece no diálogo e some ao editar o nome', async ({ page, consoleErrors }) => {
  const repo = await openRepo(page)
  await repo.getByTestId('branch-chip').click()
  await page.getByTestId('branch-search').fill('feat')
  await page.getByTestId('branch-create').click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByTestId('branch-name')).toHaveValue('feat')
  await dialog.getByTestId('confirm-ok').click()
  await expect(dialog.getByTestId('branch-error')).toContainText('feat')
  // The browser logs the refused request as a console error: it is the expected one.
  expect(consoleErrors.filter((m) => !m.includes('400') && !m.includes('409'))).toEqual([])
  consoleErrors.length = 0
  await dialog.getByTestId('branch-name').fill('feat-ok')
  await expect(dialog.getByTestId('branch-error')).toHaveCount(0)
  await dialog.getByTestId('confirm-cancel').click()
  await expect(dialog).toHaveCount(0)
  await expect(repo.getByTestId('branch-chip')).toHaveText('main')
  await expect(repo.getByTestId('branch-chip')).toBeFocused()
})
