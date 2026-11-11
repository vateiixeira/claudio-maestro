import { realpathSync, unlinkSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { expect, test } from './fixtures'

test('Git filtra repositórios e abre o histórico direto', async ({ page, request }) => {
  const response = await request.get('/api/projects', { headers: { 'X-Maestro': '1' } })
  const project = (await response.json() as { id: number; name: string; path: string }[]).find(item => item.name === 'Histórico Demo')!
  expect(project.path).toContain('maestro-e2e-')
  await page.goto(`/projects/${project.id}?visao=git`)
  await expect(page.getByTestId('scm-repo')).toHaveCount(2)
  await expect(page.getByTestId('commits-section')).toHaveCount(0)

  await page.getByTestId('git-repo-search').fill('sem-correspondencia-e2e')
  await expect(page.getByTestId('git-filter-empty')).toBeVisible()
  await expect(page.getByTestId('scm-repo')).toHaveCount(0)
  await page.getByTestId('git-clear-filters').click()
  await expect(page.getByTestId('scm-repo')).toHaveCount(2)
  await page.getByTestId('git-pending-filter').click()
  await expect(page.getByTestId('git-pending-filter')).toHaveAttribute('aria-pressed', 'true')
  await page.getByTestId('git-all-filter').click()
  await expect(page.getByTestId('scm-repo')).toHaveCount(2)

  const api = page.getByTestId('scm-repo').filter({ has: page.getByTestId('repo-short-name').filter({ hasText: /^api$/ }) })
  const toggle = api.getByTestId('scm-repo-toggle')
  if (await toggle.getAttribute('aria-expanded') !== 'true') await toggle.click()
  await api.getByTestId('repo-history').click()
  await expect(page.getByTestId('scm-section')).toBeHidden()
  await expect(page.getByTestId('commits-repo')).toHaveCount(1)
  await expect(page.getByTestId('commits-repo-toggle')).toHaveAttribute('aria-expanded', 'true')
  await expect(page.getByTestId('commit-row').first()).toBeVisible()
  await page.getByTestId('git-all-history').click()
  await expect(page.getByTestId('commits-repo')).toHaveCount(2)
  await page.getByTestId('git-view-changes').click()
  await expect(page.getByTestId('commits-section')).toBeHidden()
  await expect(toggle).toHaveAttribute('aria-expanded', 'true')

  for (const width of [360, 768, 1280]) {
    await page.setViewportSize({ width, height: 900 })
    await expect(page.getByTestId('git-repo-search')).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  }
})


test('rascunho permanece ao alternar histórico e filtrar um repositório com arquivo alterado', async ({ page, request }) => {
  const response = await request.get('/api/projects', { headers: { 'X-Maestro': '1' } })
  const project = (await response.json() as { id: number; name: string; path: string }[]).find(item => item.name === 'Histórico Demo')!
  const root = realpathSync(project.path)
  expect(root).toContain('/maestro-e2e-')
  const repoPath = realpathSync(join(root, 'api'))
  expect(repoPath).toBe(join(root, 'api'))
  const file = join(repoPath, 'audit-draft-preservation.e2e.txt')
  writeFileSync(file, 'Arquivo temporário para verificar o rascunho, sem commit.\n', { flag: 'wx' })
  try {
    await page.goto(`/projects/${project.id}?visao=git`)
    const repo = page.getByTestId('scm-repo').filter({ has: page.getByTestId('repo-short-name').filter({ hasText: /^api$/ }) })
    await expect(repo).toBeVisible()
    await page.getByTestId('scm-refresh').click()
    await expect(repo.getByTestId('scm-file').filter({ hasText: 'audit-draft-preservation.e2e.txt' })).toBeVisible()
    const message = repo.getByTestId('commit-message')
    await expect(message).toBeVisible()
    await message.fill('Rascunho visual sem commit')
    await repo.getByTestId('repo-history').click()
    await expect(page.getByTestId('commits-section')).toBeVisible()
    await page.getByTestId('git-view-changes').click()
    await expect(message).toHaveValue('Rascunho visual sem commit')
    await page.getByTestId('git-repo-search').fill('sem-correspondencia-e2e')
    await expect(repo).toHaveCount(0)
    await page.getByTestId('git-clear-filters').click()
    await expect(message).toHaveValue('Rascunho visual sem commit')
    await page.reload()
    await expect(message).toHaveValue('Rascunho visual sem commit')
  } finally {
    unlinkSync(file)
  }
})
