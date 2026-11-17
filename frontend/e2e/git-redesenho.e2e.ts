import { execFileSync } from 'node:child_process'
import { realpathSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import type { APIRequestContext, Page } from '@playwright/test'
import { expect, test } from './fixtures'

// The redesigned Git panel (screens 16 and 20). Each test uses a seeded project of its own and
// leaves it as it found it, because the other git specs share the same database.

async function projectOf(request: APIRequestContext, name: string): Promise<{ id: number; path: string }> {
  const response = await request.get('/api/projects', { headers: { 'X-Maestro': '1' } })
  const found = ((await response.json()) as { id: number; name: string; path: string }[]).find((item) => item.name === name)!
  expect(found.path).toContain('maestro-e2e-')
  return { id: found.id, path: realpathSync(found.path) }
}

const repoRow = (page: Page, name: string) =>
  page.getByTestId('scm-repo').filter({ has: page.getByTestId('repo-short-name').filter({ hasText: new RegExp(`^${name}$`) }) })

const noHorizontalScroll = (page: Page) =>
  page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)

test('caixa de commit: rascunho de várias linhas sobrevive ao recarregar e Enter só quebra a linha', async ({ page, request }) => {
  const project = await projectOf(request, 'Alterações Demo')
  const git = (...args: string[]) => execFileSync('git', ['-C', project.path, '-c', 'core.fsmonitor=false', ...args], { encoding: 'utf8' })
  // Other specs leave the repository in different states: start from "nothing staged" and add
  // two new files and one more edit, so the count below does not depend on the order they ran.
  git('reset', '-q')
  const readme = join(project.path, 'README.md')
  const original = readFileSync(readme, 'utf8')
  const created = ['redesenho-a.txt', 'redesenho-b.txt'].map((name) => join(project.path, name))
  try {
    for (const file of created) writeFileSync(file, 'novo\n', { flag: 'wx' })
    writeFileSync(readme, `${original}\nLinha do redesenho.\n`)
    const total = git('status', '--porcelain', '-uall').split('\n').filter(Boolean).length

    const posts: string[] = []
    page.on('request', (item) => {
      if (item.method() === 'POST' && /\/git\//.test(item.url())) posts.push(new URL(item.url()).pathname)
    })
    await page.goto(`/projects/${project.id}?visao=git`)
    const repo = page.getByTestId('scm-repo').first()
    await expect(repo.getByTestId('scm-file')).toHaveCount(total)

    // Every file says what happened to it, in words.
    await expect(repo.locator('[data-test="scm-file"][data-path="README.md"]').getByTestId('file-status')).toHaveText('modificado')
    for (const name of ['redesenho-a.txt', 'redesenho-b.txt']) {
      await expect(repo.locator(`[data-test="scm-file"][data-path="${name}"]`).getByTestId('file-status')).toHaveText('novo')
    }
    // Nothing staged: the button says how many files it would take.
    const primary = repo.getByTestId('primary-action')
    await expect(primary).toHaveText(`Commitar ${total} arquivos`)
    await expect(repo.getByTestId('commit-caption')).toHaveText(/^Commit em main$/i)

    const message = repo.getByTestId('commit-message')
    await expect(message).toHaveJSProperty('tagName', 'TEXTAREA')
    await message.fill('Primeira linha')
    await message.press('Enter')
    await message.pressSequentially('Segunda linha')
    await expect(message).toHaveValue('Primeira linha\nSegunda linha')
    // Enter broke the line: it neither committed nor touched the network.
    await expect(primary).toHaveText(`Commitar ${total} arquivos`)
    expect(posts).toEqual([])

    await page.reload()
    await expect(page.getByTestId('scm-repo').first().getByTestId('commit-message')).toHaveValue('Primeira linha\nSegunda linha')
    await page.getByTestId('scm-repo').first().getByTestId('commit-message').fill('')
  } finally {
    for (const file of created) rmSync(file, { force: true })
    writeFileSync(readme, original)
  }
})

test('repositório aberto lista o que o Push leva e o menu abre o histórico', async ({ page, request }) => {
  const project = await projectOf(request, 'Histórico Demo')
  await page.goto(`/projects/${project.id}?visao=git`)

  // One repository has something pending: the tab says so, and the totals line says what.
  await expect(page.getByRole('tab', { name: /^Git/ })).toContainText('1 com pendências')
  await expect(page.getByTestId('scm-summary')).toContainText('2 commits para enviar em 1 repositório')
  await expect(page.getByTestId('scm-summary')).toContainText('1 para baixar')

  // `api` has commits to send and to pull at once, so it starts open.
  const api = repoRow(page, 'api')
  await expect(api.getByTestId('scm-body')).toBeVisible()
  await expect(api.getByTestId('primary-action')).toHaveText('Sincronizar 1↓ 2↑')
  const outgoing = api.getByTestId('scm-outgoing')
  await expect(outgoing).toContainText('Para enviar')
  await expect(outgoing.getByTestId('scm-outgoing-count')).toHaveText('2')
  await expect(outgoing).toContainText('o que o Push leva para o remoto')
  await expect(outgoing.getByTestId('scm-outgoing-commit')).toHaveText([/Ajustar a rota 35/, /Ajustar a rota 34/])

  // "⋯" > "Ver commits" opens the history of that repository only.
  await api.getByTestId('repo-more').click()
  await page.getByTestId('menu-history').click()
  await expect(page.getByTestId('scm-section')).toBeHidden()
  await expect(page.getByTestId('commits-repo')).toHaveCount(1)
  await expect(page.getByTestId('commit-row').first()).toBeVisible()
})

test('linha do repositório: Pull e Push com a contagem cabem em 360, 768, 1024 e 1440', async ({ page, request }) => {
  const project = await projectOf(request, 'Histórico Demo')
  await page.goto(`/projects/${project.id}?visao=git`)
  const api = repoRow(page, 'api')
  await expect(api.getByTestId('repo-pull')).toHaveText(/^Pull 1$/)
  await expect(api.getByTestId('repo-push')).toHaveText(/^Push 2$/)
  for (const width of [360, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: 900 })
    expect(await noHorizontalScroll(page)).toBe(true)
    for (const id of ['repo-pull', 'repo-push', 'repo-more']) {
      const box = (await api.getByTestId(id).boundingBox())!
      expect(box.x).toBeGreaterThanOrEqual(0)
      expect(box.x + box.width).toBeLessThanOrEqual(width)
    }
  }
})

test('teclado: a linha abre e fecha com Enter e Espaço, e o menu devolve o foco', async ({ page, request }) => {
  const project = await projectOf(request, 'Histórico Demo')
  await page.goto(`/projects/${project.id}?visao=git`)
  const web = repoRow(page, 'web')
  const toggle = web.getByTestId('scm-repo-toggle')
  await expect(toggle).toHaveAttribute('aria-expanded', 'false')
  await toggle.focus()
  await page.keyboard.press('Enter')
  await expect(toggle).toHaveAttribute('aria-expanded', 'true')
  await page.keyboard.press('Space')
  await expect(toggle).toHaveAttribute('aria-expanded', 'false')

  const more = web.getByTestId('repo-more')
  await more.focus()
  await page.keyboard.press('Enter')
  await expect(page.getByTestId('menu-history')).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(page.getByTestId('repo-menu')).toHaveCount(0)
  await expect(more).toBeFocused()
})

test('muitos repositórios: dois grupos, e o menu abre por cima da linha seguinte', async ({ page, request }) => {
  const project = await projectOf(request, 'Ramos Demo')
  await page.goto(`/projects/${project.id}?visao=git`)
  await expect(page.getByTestId('scm-repo')).toHaveCount(3)
  // Nothing pending: one group only, and the tab has no badge.
  await expect(page.getByRole('group', { name: 'Sem pendências' })).toBeVisible()
  await expect(page.getByRole('group', { name: 'Com pendências' })).toHaveCount(0)
  await expect(page.getByRole('tab', { name: /^Git/ })).not.toContainText('com pendências')
  await expect(page.getByTestId('scm-summary')).toContainText('3 sem upstream')

  // The "⋯" menu of a row covers the row below it, and a click outside closes it.
  const first = page.getByTestId('scm-repo').first()
  const second = page.getByTestId('scm-repo').nth(1)
  await first.getByTestId('repo-more').click()
  const menu = page.getByTestId('repo-menu')
  await expect(menu).toBeVisible()
  const target = (await second.getByTestId('scm-repo-toggle').boundingBox())!
  const menuBox = (await menu.boundingBox())!
  expect(menuBox.y + menuBox.height).toBeGreaterThan(target.y + target.height / 2)
  // Pick a point that is inside both the menu and the second row.
  const point = { x: menuBox.x + menuBox.width / 2, y: target.y + target.height / 2 }
  expect(await page.evaluate(({ x, y }) => !!document.elementFromPoint(x, y)?.closest('[data-test="repo-menu"]'), point)).toBe(true)
  await page.mouse.click(10, 10)
  await expect(menu).toHaveCount(0)
})

test('muitos repositórios: um repositório com alteração sobe para o grupo "Com pendências" e volta', async ({ page, request }) => {
  const project = await projectOf(request, 'Ramos Demo')
  const file = join(project.path, 'docs', 'redesenho-grupos.txt')
  try {
    await page.goto(`/projects/${project.id}?visao=git`)
    await expect(page.getByTestId('scm-repo')).toHaveCount(3)
    await expect(page.getByRole('group', { name: 'Sem pendências' }).getByTestId('group-header-count')).toHaveText('3')
    writeFileSync(file, 'novo\n', { flag: 'wx' })
    await page.getByTestId('scm-refresh').click()

    const pending = page.getByRole('group', { name: 'Com pendências' })
    const clear = page.getByRole('group', { name: 'Sem pendências' })
    await expect(pending.getByTestId('group-header-count')).toHaveText('1')
    await expect(clear.getByTestId('group-header-count')).toHaveText('2')
    await expect(pending.getByTestId('scm-repo')).toHaveCount(1)
    await expect(pending.getByTestId('repo-short-name')).toHaveText('docs')
    await expect(pending.getByTestId('scm-file')).toHaveCount(1)
    await expect(page.getByRole('tab', { name: /^Git/ })).toContainText('1 com pendências')
    await expect(page.getByTestId('scm-summary')).toContainText('1 alteração')
  } finally {
    rmSync(file, { force: true })
  }
  await page.getByTestId('scm-refresh').click()
  await expect(page.getByRole('group', { name: 'Com pendências' })).toHaveCount(0)
  await expect(page.getByRole('group', { name: 'Sem pendências' }).getByTestId('group-header-count')).toHaveText('3')
})
