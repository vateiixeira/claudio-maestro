import { execFileSync } from 'node:child_process'
import { mkdirSync, rmSync, writeFileSync } from 'node:fs'
import { resolve, join } from 'node:path'
import type { APIRequestContext, Page } from '@playwright/test'
import { expect, test } from './fixtures'

async function project(request: APIRequestContext, name: string) {
  const response = await request.get('/api/projects', { headers: { 'X-Maestro': '1' } })
  const result = (await response.json() as { id: number; name: string; path: string }[]).find(p => p.name === name)!
  expect(result.path).toContain('maestro-e2e-')
  return result
}

async function openProject(page: Page, name: string) {
  await page.goto('/inbox')
  const nav = page.getByRole('navigation', { name: 'Navegação' })
  await nav.getByRole('button', { name: /sem conversa aberta/ }).click()
  await nav.getByRole('link', { name: new RegExp(name) }).first().click()
  await expect(page.getByTestId('scm-section')).toBeVisible()
}

function git(path: string, ...args: string[]): string {
  return execFileSync('git', ['-C', path, '-c', 'core.hooksPath=/dev/null', ...args], { encoding: 'utf8' }).trim()
}

test('abrir projeto mostra detalhes enquanto o resumo ainda está pendente', async ({ page, request }) => {
  const data = await project(request, 'Alterações Demo')
  let release!: () => void
  const blocked = new Promise<void>(resolve => { release = resolve })
  let summaries = 0
  await page.route(`**/api/projects/${data.id}/git`, async route => {
    summaries++
    await blocked
    await route.fulfill({ json: { repos: [], limit_reached: false } })
  })
  const summaryReturned = page.waitForResponse(response => new URL(response.url()).pathname === `/api/projects/${data.id}/git`)
  try {
    await openProject(page, 'Alterações Demo')
    await expect(page.getByTestId('scm-repo').first()).toBeVisible()
    await expect(page.getByTestId('scm-file').first()).toBeVisible()
    expect(summaries).toBe(1)
  } finally {
    release()
  }
  await summaryReturned
  await expect(page.getByTestId('scm-repo').first()).toBeVisible()
})

test('comparar branches sem checkout: dois sentidos, arquivos, paginação e base persistida', async ({ page, request }) => {
  const data = await project(request, 'Histórico Demo')
  const path = join(data.path, 'api')
  const branch = 'e2e/base-comparacao'
  const before = git(path, 'rev-parse', 'HEAD')
  git(path, 'branch', branch, 'main~34')
  const comparisons: string[] = []
  page.on('request', request => { if (request.url().includes('/git/comparison')) comparisons.push(request.url()) })
  try {
    await openProject(page, 'Histórico Demo')
    const repo = page.getByTestId('commits-repo').filter({ hasText: 'api' })
    await repo.getByTestId('commits-repo-toggle').click()
    const node = repo.getByTestId('branch-comparison')
    await expect(node).toBeVisible()
    expect(comparisons).toEqual([])
    await node.getByTestId('comparison-toggle').click()
    await expect(node.getByTestId('comparison-ahead-toggle')).toContainText('2 commits')
    await expect(node.getByTestId('comparison-behind-toggle')).toContainText('1 commit')
    await node.getByTestId('comparison-ahead-toggle').click()
    const ahead = node.getByTestId('comparison-direction').first()
    await expect(ahead.getByTestId('commit-row')).toHaveCount(2)
    await ahead.getByTestId('comparison-files-toggle').click()
    await ahead.getByTestId('comparison-file').filter({ hasText: 'rota35.txt' }).click()
    await expect(ahead.locator('[data-test="diff-line"][data-kind="add"]')).toContainText('Ajustar a rota 35')
    await node.getByTestId('comparison-behind-toggle').click()
    await expect(node.getByTestId('comparison-direction').last()).toContainText('Corrigir o cabeçalho no remoto')
    await node.getByTestId('comparison-select').click()
    await page.getByRole('option', { name: branch, exact: true }).click()
    await node.getByTestId('comparison-ahead-toggle').click()
    await expect(ahead.getByTestId('commit-row')).toHaveCount(30)
    await ahead.getByTestId('comparison-load-more').click()
    await expect(ahead.getByTestId('commit-row')).toHaveCount(34)
    await expect(ahead.getByTestId('comparison-load-more')).toHaveCount(0)
    expect(git(path, 'rev-parse', 'HEAD')).toBe(before)
    expect(git(path, 'symbolic-ref', 'HEAD')).toBe('refs/heads/main')
    await page.reload()
    await expect(repo.getByTestId('commits-repo-toggle')).toHaveAttribute('aria-expanded', 'true')
    await expect(node.getByTestId('comparison-toggle')).toContainText(branch)
  } finally { git(path, 'branch', '-D', branch) }
})

test('uma carga de detalhes e preparar sem reler histórico; expansão lembrada', async ({ page, request }) => {
  const data = await project(request, 'Alterações Demo')
  const file = 'e2e-rea-stage.txt'
  writeFileSync(join(data.path, file), 'Arquivo exclusivo do teste REA\n')
  const details: string[] = []
  const logs: string[] = []
  page.on('request', request => {
    const url = new URL(request.url())
    if (url.pathname.endsWith('/git/details')) details.push(url.href)
    if (url.pathname.endsWith('/git/log')) logs.push(url.href)
  })
  try {
    await page.clock.install()
    await openProject(page, 'Alterações Demo')
    const commits = page.getByTestId('commits-repo').first()
    await expect(commits.getByTestId('commits-repo-toggle')).toHaveAttribute('aria-expanded', 'true')
    await expect(commits.getByTestId('commit-row').first()).toBeVisible()
    expect(details).toHaveLength(1)
    const initialLogs = logs.length
    const scm = page.getByTestId('scm-repo').first()
    const row = scm.locator(`[data-test="scm-file"][data-path="${file}"]`)
    await row.hover()
    const started = Date.now()
    await row.getByTestId('file-stage').click()
    await expect(scm.locator('[data-group="staged"]').getByTestId('scm-file').filter({ hasText: file })).toBeVisible()
    const stageToVisibleMs = Date.now() - started
    await page.clock.runFor(1000)
    expect(details).toHaveLength(1)
    expect(logs).toHaveLength(initialLogs)
    const result = { initialDetailsRequests: details.length, initialLogRequests: initialLogs, stageLogRequests: logs.length - initialLogs, stageToVisibleMs }
    const output = resolve('..', 'docs/research/2026-11-11-git-rea/screenshots')
    mkdirSync(output, { recursive: true })
    writeFileSync(join(output, 'git-panel-requests.json'), JSON.stringify(result, null, 2))
    await page.setViewportSize({ width: 1440, height: 1000 })
    await page.getByTestId('repos').screenshot({ path: join(output, 'git-changes-focused.png') })
    await test.info().attach('git-panel-requests', { body: JSON.stringify(result, null, 2), contentType: 'application/json' })
    await commits.getByTestId('commits-repo-toggle').click()
    await scm.getByTestId('scm-repo-toggle').click()
    await page.reload()
    await expect(commits.getByTestId('commits-repo-toggle')).toHaveAttribute('aria-expanded', 'false')
    await expect(scm.getByTestId('scm-repo-toggle')).toHaveAttribute('aria-expanded', 'false')
  } finally {
    git(data.path, 'reset', '-q', 'HEAD', '--', file)
    rmSync(join(data.path, file), { force: true })
  }
})

test('painel Git cabe em telas estreitas e temas, com capturas de referência', async ({ page }) => {
  const output = resolve('..', 'docs/research/2026-11-11-git-rea/screenshots')
  mkdirSync(output, { recursive: true })
  await openProject(page, 'Histórico Demo')
  const api = page.getByTestId('commits-repo').filter({ hasText: 'api' })
  await api.getByTestId('commits-repo-toggle').click()
  await expect(api.getByTestId('commit-row').first()).toBeVisible()
  await api.getByTestId('comparison-toggle').click()
  await expect(api.getByTestId('comparison-ahead-toggle')).toBeVisible()
  const metrics = []
  for (const width of [360, 768, 1440]) {
    await page.setViewportSize({ width, height: 1000 })
    const section = page.getByTestId('commits-section')
    await expect(section).toBeVisible()
    const box = (await section.boundingBox())!
    expect(box.x).toBeGreaterThanOrEqual(0)
    expect(box.x + box.width).toBeLessThanOrEqual(width + 1)
    await api.getByTestId('history-ref').click()
    const menu = page.getByRole('listbox', { name: 'Branches' })
    await expect(menu).toBeVisible()
    const menuBox = (await menu.boundingBox())!
    expect(menuBox.x).toBeGreaterThanOrEqual(0)
    expect(menuBox.x + menuBox.width).toBeLessThanOrEqual(width + 1)
    await page.getByRole('textbox', { name: 'Procurar branch' }).press('Escape')
    await page.screenshot({ path: join(output, `git-${width}.png`), fullPage: true })
    if (width === 1440) await section.locator('..').screenshot({ path: join(output, 'git-panel-focused.png') })
    metrics.push({ width, rows: await api.getByTestId('commit-row').count(), widthOfSection: box.width })
  }
  for (const theme of ['dracula', 'monokai-pro', 'monokai-machine', 'monokai-octagon', 'monokai-ristretto', 'monokai-spectrum', 'monokai-classic']) {
    await page.evaluate(theme => document.documentElement.setAttribute('data-theme', theme), theme)
    await page.screenshot({ path: join(output, `git-theme-${theme}.png`), fullPage: true })
  }
  await page.evaluate(() => { document.documentElement.removeAttribute('data-theme'); document.documentElement.style.zoom = '2' })
  await page.screenshot({ path: join(output, 'git-css-zoom-200.png'), fullPage: true })
  await test.info().attach('git-layout', { body: JSON.stringify({ metrics, zoom: 'CSS zoom 200%, não zoom nativo do navegador' }, null, 2), contentType: 'application/json' })
})
