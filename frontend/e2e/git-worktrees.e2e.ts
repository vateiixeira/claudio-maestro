import { execFileSync } from 'node:child_process'
import { existsSync, mkdirSync, realpathSync, rmdirSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { expect, test } from './fixtures'

const git = (directory: string, ...args: string[]) => execFileSync('git', [
  '-C', directory, '-c', 'core.hooksPath=/dev/null', '-c', 'core.fsmonitor=false',
  '-c', 'commit.gpgsign=false', '-c', 'user.name=E2E', '-c', 'user.email=e2e@example.invalid', ...args,
], { encoding: 'utf8' }).trim()

test('worktrees oculta e externa aparecem com histórico, diff e preparação isolados', async ({ page, request }) => {
  const response = await request.get('/api/projects', { headers: { 'X-Maestro': '1' } })
  const project = (await response.json() as { id: number; name: string; path: string }[]).find(item => item.name === 'Alterações Demo')!
  const root = realpathSync(project.path)
  expect(root).toContain('/maestro-e2e-')
  const hiddenParent = join(root, '.worktrees')
  const madeParent = !existsSync(hiddenParent)
  mkdirSync(hiddenParent, { recursive: true })
  const worktrees = [
    { path: join(hiddenParent, 'e2e-hidden-worktree'), name: 'e2e-hidden-worktree', branch: 'e2e/hidden-worktree' },
    { path: join(dirname(root), 'e2e-external-worktree'), name: 'e2e-external-worktree', branch: 'e2e/external-worktree' },
  ]
  const created: typeof worktrees = []
  const mainHead = git(root, 'rev-parse', 'HEAD')
  const mainIndex = git(root, 'diff', '--cached', '--name-status')
  const file = 'e2e-worktree-only.txt'
  expect(existsSync(join(root, file))).toBe(false)
  try {
    for (const worktree of worktrees) {
      expect(resolve(worktree.path)).toContain('/maestro-e2e-')
      expect(existsSync(worktree.path)).toBe(false)
      git(root, 'worktree', 'add', '-b', worktree.branch, worktree.path, 'HEAD')
      created.push(worktree)
      expect(realpathSync(worktree.path)).toBe(worktree.path)
      writeFileSync(join(worktree.path, file), `original ${worktree.name}\n`, { flag: 'wx' })
      git(worktree.path, 'add', '--', file)
      git(worktree.path, 'commit', '-m', `Commit exclusivo ${worktree.name}`)
      writeFileSync(join(worktree.path, file), `alterado ${worktree.name}\n`)
    }
    await page.goto(`/projects/${project.id}`)
    await expect(page.getByTestId('scm-repo')).toHaveCount(3)
    await expect(page.getByTestId('commits-repo')).toHaveCount(3)
    for (const worktree of worktrees) {
      const scm = page.getByTestId('scm-repo').filter({ hasText: worktree.name })
      const history = page.getByTestId('commits-repo').filter({ hasText: worktree.name })
      await expect(scm).toHaveCount(1)
      await expect(history).toHaveCount(1)
      if (await history.getByTestId('commits-repo-toggle').getAttribute('aria-expanded') !== 'true') await history.getByTestId('commits-repo-toggle').click()
      await expect(history.getByTestId('commit-row').first()).toContainText(`Commit exclusivo ${worktree.name}`)
      if (await scm.getByTestId('scm-repo-toggle').getAttribute('aria-expanded') !== 'true') await scm.getByTestId('scm-repo-toggle').click()
      const changes = scm.locator('[data-test="scm-group"][data-group="changes"]')
      const staged = scm.locator('[data-test="scm-group"][data-group="staged"]')
      const row = changes.getByTestId('scm-file').filter({ hasText: file })
      await row.getByTestId('file-open').click()
      const dialog = page.getByRole('dialog')
      await expect(dialog).toContainText(worktree.path)
      await expect(dialog.locator('[data-test="diff-line"][data-kind="add"]')).toContainText(`alterado ${worktree.name}`)
      await page.keyboard.press('Escape')
      await row.hover()
      await row.getByTestId('file-stage').click()
      await expect(row).toHaveCount(0)
      const prepared = staged.getByTestId('scm-file').filter({ hasText: file })
      await prepared.getByTestId('file-open').click()
      await expect(dialog).toContainText(worktree.path)
      await expect(dialog.locator('[data-test="diff-line"][data-kind="add"]')).toContainText(`alterado ${worktree.name}`)
      await page.keyboard.press('Escape')
      await prepared.hover()
      await prepared.getByTestId('file-unstage').click()
      await expect(prepared).toHaveCount(0)
      await row.getByTestId('file-open').click()
      await expect(dialog).toContainText(worktree.path)
      await expect(dialog.locator('[data-test="diff-line"][data-kind="add"]')).toContainText(`alterado ${worktree.name}`)
      await page.keyboard.press('Escape')
      expect(git(worktree.path, 'diff', '--cached', '--name-only')).toBe('')
      expect(git(worktree.path, 'diff', '--name-only')).toBe(file)
    }
    expect(git(root, 'rev-parse', 'HEAD')).toBe(mainHead)
    expect(git(root, 'diff', '--cached', '--name-status')).toBe(mainIndex)
    expect(existsSync(join(root, file))).toBe(false)
  } finally {
    for (const worktree of created.reverse()) {
      expect(worktree.path).toContain('/maestro-e2e-')
      git(root, 'worktree', 'remove', '--force', worktree.path)
      git(root, 'branch', '-D', worktree.branch)
    }
    if (madeParent) rmdirSync(hiddenParent)
  }
})
