import { execFileSync } from 'node:child_process'
import { dirname, join } from 'node:path'
import { rmSync, writeFileSync } from 'node:fs'
import { expect, test } from './fixtures'

type Page = import('@playwright/test').Page
type Locator = import('@playwright/test').Locator

async function openProject(page: Page) {
  await page.goto('/inbox')
  const nav = page.getByRole('navigation', { name: 'Navegação' })
  // The project has no conversation, so the sidebar keeps it under "Outros projetos".
  await nav.getByRole('button', { name: /sem conversa aberta/ }).click()
  await nav.getByRole('link', { name: /Sincronia Demo/ }).first().click()
  await page.getByRole('tab', { name: /^Git/ }).click()
  await expect(page.getByTestId('scm-repo')).toHaveCount(2)
}

const repo = (page: Page, name: string) =>
  page.locator('[data-test="scm-repo"]').filter({ has: page.locator('[data-test="scm-repo-toggle"]', { hasText: name }) })

test.describe.configure({ mode: 'serial' })

/** Rereads one repository through its "⋯" menu (the row no longer has a refresh icon). */
async function refreshRepo(page: Page, row: Locator): Promise<void> {
  await row.getByTestId('repo-more').click()
  await page.getByTestId('menu-refresh').click()
}

/** A repository may open by itself when its state changes; this leaves it open either way. */
async function ensureOpen(row: Locator): Promise<void> {
  const toggle = row.getByTestId('scm-repo-toggle')
  await expect(async () => {
    if (await toggle.getAttribute('aria-expanded') !== 'true') await toggle.click()
    await expect(toggle).toHaveAttribute('aria-expanded', 'true', { timeout: 1_000 })
  }).toPass()
  await expect(row.getByTestId('scm-body')).toBeVisible()
}

test('sincronizar, publicar e buscar no remoto', async ({ page }) => {
  await openProject(page)
  const loja = repo(page, 'loja')
  await expect(loja.getByTestId('primary-action')).toHaveText('Sincronizar 1↓ 1↑')
  await loja.getByTestId('primary-action').click()
  await expect(loja.getByTestId('sync-counts')).toHaveText('em dia')
  await expect(loja.getByTestId('primary-action')).toHaveCount(0)
  await expect(loja.getByTestId('commit-message')).toHaveCount(0)

  const site = repo(page, 'site')
  await ensureOpen(site)
  await expect(site.getByTestId('primary-action')).toHaveText('Publicar branch em origin')
  await site.getByTestId('primary-action').click()
  await expect(site.getByTestId('sync-counts')).toHaveText('em dia')

  await loja.getByTestId('repo-more').click()
  await page.getByTestId('menu-fetch').click()
  await expect(loja.getByTestId('scm-error')).toHaveCount(0)
  await page.getByTestId('scm-fetch-all').click()
  await expect(page.getByTestId('scm-fetch-all')).toBeEnabled()
  await expect(page.locator('[data-test="scm-error"]')).toHaveCount(0)
})

// The tests below run after the first one, which leaves `loja` in sync with its remote, and each
// one leaves it in sync again. The remote is a bare folder inside the temporary root.
const ids = ['-c', 'user.name=E2E', '-c', 'user.email=e2e@example.com']
const git = (cwd: string, ...args: string[]) => execFileSync('git', ['-C', cwd, ...ids, ...args], { encoding: 'utf8' }).trim()

async function lojaPath(page: Page): Promise<string> {
  const path = await repo(page, 'loja').getAttribute('data-repo')
  expect(path).toBeTruthy()
  return path as string
}

/** Puts a commit on the remote through a throwaway clone next to the bare repository. */
function commitOnRemote(local: string, file: string): void {
  const bare = git(local, 'remote', 'get-url', 'origin')
  const clone = join(dirname(bare), `clone-${file}`)
  try {
    execFileSync('git', ['clone', '-q', bare, clone])
    writeFileSync(join(clone, file), `${file}\n`)
    git(clone, 'add', file)
    git(clone, 'commit', '-q', '-m', `Remoto: ${file}`)
    git(clone, 'push', '-q', 'origin', 'main')
  } finally {
    rmSync(clone, { recursive: true, force: true })
  }
}

/** The browser logs every 409 the app handles on purpose; those are expected here, nothing else is. */
function expectRefusal(consoleErrors: string[]): void {
  expect(consoleErrors.length).toBeGreaterThan(0)
  const unexpected = consoleErrors.filter((text) => !text.includes('status of 409'))
  consoleErrors.length = 0
  expect(unexpected).toEqual([])
}

function commitLocal(local: string, file: string): void {
  writeFileSync(join(local, file), `${file}\n`)
  git(local, 'add', file)
  git(local, 'commit', '-q', '-m', `Local: ${file}`)
}

test('enviar puro: o botão largo e o ícone seguem o estado, e a seção Commits atualiza', async ({ page }) => {
  await openProject(page)
  const loja = repo(page, 'loja')
  const local = await lojaPath(page)
  commitLocal(local, 'so-envio.md')
  await refreshRepo(page, loja)
  // Only ahead: the repository starts collapsed and the row offers just Push, with the count.
  await expect(loja.getByTestId('repo-push')).toHaveText('Push 1')
  await expect(loja.getByTestId('repo-pull')).toHaveCount(0)
  await loja.getByTestId('scm-repo-toggle').click()
  await expect(loja.getByTestId('primary-action')).toHaveText('Enviar 1 commit')
  await expect(loja.getByTestId('repo-pull')).toBeDisabled()
  await expect(loja.getByTestId('repo-pull')).toHaveAttribute('title', 'Nada para baixar')
  await page.getByTestId('git-view-commits').click()
  const commits = page.getByTestId('commits-repo').filter({ hasText: 'loja' })
  await commits.getByTestId('commits-repo-toggle').click()
  await expect(commits.getByTestId('group-outgoing')).toContainText('Para subir — 1 commit')
  await page.getByTestId('git-view-changes').click()
  await loja.getByTestId('primary-action').click()
  await expect(loja.getByTestId('sync-counts')).toHaveText('em dia')
  await page.getByTestId('git-view-commits').click()
  await commits.getByTestId('apply-history-update').click()
  await expect(commits.getByTestId('group-outgoing')).toContainText('Para subir — nenhum')
  await page.getByTestId('git-view-changes').click()
  await expect(loja.getByTestId('repo-push')).toBeDisabled()
  await expect(loja.getByTestId('repo-push')).toHaveAttribute('title', 'Nada para enviar')
})

test('baixar puro: o botão largo baixa e a seção Commits mostra o grupo Para baixar antes', async ({ page }) => {
  await openProject(page)
  const loja = repo(page, 'loja')
  commitOnRemote(await lojaPath(page), 'so-baixar.md')
  await loja.getByTestId('repo-more').click()
  await page.getByTestId('menu-fetch').click()
  // Only behind: the collapsed row offers just Pull, with the count.
  await expect(loja.getByTestId('repo-pull')).toHaveText('Pull 1')
  await expect(loja.getByTestId('repo-push')).toHaveCount(0)
  await ensureOpen(loja)
  await expect(loja.getByTestId('primary-action')).toHaveText('Baixar 1 commit')
  await expect(loja.getByTestId('repo-push')).toBeDisabled()
  await page.getByTestId('git-view-commits').click()
  const commits = page.getByTestId('commits-repo').filter({ hasText: 'loja' })
  await commits.getByTestId('commits-repo-toggle').click()
  await expect(commits.getByTestId('group-incoming')).toContainText('Para baixar — 1 commit')
  await page.getByTestId('git-view-changes').click()
  await loja.getByTestId('primary-action').click()
  await expect(loja.getByTestId('sync-counts')).toHaveText('em dia')
  await page.getByTestId('git-view-commits').click()
  await commits.getByTestId('apply-history-update').click()
  await expect(commits.getByTestId('group-incoming')).toContainText('Para baixar — nenhum')
})

test('envio recusado: o erro aparece com o repositório recolhido, mostra a saída e fecha', async ({ page, consoleErrors }) => {
  await openProject(page)
  const loja = repo(page, 'loja')
  const local = await lojaPath(page)
  commitOnRemote(local, 'remoto-na-frente.md')
  commitLocal(local, 'local-atrasado.md')
  // Not fetched: the app still believes there is nothing to pull, so Enviar is on and git refuses.
  await refreshRepo(page, loja)
  // `loja` was collapsed when the page loaded and stays so; the row offers Push with the count.
  await expect(loja.getByTestId('scm-body')).toHaveCount(0)
  await expect(loja.getByTestId('repo-push')).toBeEnabled()
  await expect(loja.getByTestId('repo-push')).toHaveText('Push 1')
  await loja.getByTestId('repo-push').click()
  const error = loja.getByTestId('scm-error')
  await expect(error).toBeVisible()
  await expect(error).toContainText('Sincronize para baixar e enviar')
  await error.getByTestId('show-output').click()
  await expect(loja.getByTestId('scm-error-output')).toContainText('rejected')
  await loja.getByTestId('dismiss-error').click()
  await expect(error).toHaveCount(0)
  expectRefusal(consoleErrors)

  // Recover: fetch, then sync.
  await ensureOpen(loja)
  await loja.getByTestId('repo-more').click()
  await page.getByTestId('menu-fetch').click()
  await expect(loja.getByTestId('primary-action')).toHaveText('Sincronizar 1↓ 1↑')
  await loja.getByTestId('primary-action').click()
  await expect(loja.getByTestId('sync-counts')).toHaveText('em dia')
})

test('remoto inexistente: Buscar no remoto e Buscar em todos mostram o erro na linha do repositório', async ({ page, consoleErrors }) => {
  await openProject(page)
  const loja = repo(page, 'loja')
  const local = await lojaPath(page)
  const good = git(local, 'remote', 'get-url', 'origin')
  git(local, 'remote', 'set-url', 'origin', join(dirname(good), 'nao-existe.git'))
  try {
    await loja.getByTestId('scm-repo-toggle').click()
    await loja.getByTestId('repo-more').click()
    await page.getByTestId('menu-fetch').click()
    await expect(loja.getByTestId('scm-error')).toBeVisible()
    await loja.getByTestId('dismiss-error').click()
    await expect(loja.getByTestId('scm-error')).toHaveCount(0)

    await page.getByTestId('scm-fetch-all').click()
    await expect(loja.getByTestId('scm-error')).toBeVisible()
    await expect(page.getByTestId('scm-fetch-all')).toBeEnabled()
    // The other repository is not blamed for the failure.
    await expect(repo(page, 'site').getByTestId('scm-error')).toHaveCount(0)
    expectRefusal(consoleErrors)
  } finally {
    git(local, 'remote', 'set-url', 'origin', good)
  }
})

test('menu Mais ações: teclado, Esc, foco e Copiar caminho', async ({ page }) => {
  await page.addInitScript(() => {
    const copied: string[] = []
    Object.defineProperty(window, '__copied', { value: copied })
    Object.defineProperty(navigator, 'clipboard', { value: { writeText: async (text: string) => { copied.push(text) } }, configurable: true })
  })
  await openProject(page)
  const loja = repo(page, 'loja')
  const more = loja.getByTestId('repo-more')
  const menu = loja.getByTestId('repo-menu')

  await more.click()
  await expect(menu.getByRole('menuitem')).toHaveText(['Ver commits', 'Mesclar uma branch…', 'Buscar no remoto', 'Atualizar', 'Copiar caminho'])
  await expect(menu.getByTestId('menu-abort')).toHaveCount(0)
  await expect(menu.getByTestId('menu-history')).toBeFocused()
  await page.keyboard.press('ArrowDown')
  await expect(menu.getByTestId('menu-merge')).toBeFocused()
  await page.keyboard.press('ArrowUp')
  await expect(menu.getByTestId('menu-history')).toBeFocused()
  await page.keyboard.press('ArrowUp')
  await expect(menu.getByTestId('menu-copy-path')).toBeFocused()
  await page.keyboard.press('ArrowDown')
  await expect(menu.getByTestId('menu-history')).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(menu).toHaveCount(0)
  await expect(more).toBeFocused()

  await more.click()
  await page.getByTestId('repo-menu-backdrop').click({ position: { x: 5, y: 5 } })
  await expect(menu).toHaveCount(0)

  await more.click()
  // Tab walks the five items, and the next one leaves the menu.
  for (const id of ['menu-merge', 'menu-fetch', 'menu-refresh', 'menu-copy-path']) {
    await page.keyboard.press('Tab')
    await expect(menu.getByTestId(id)).toBeFocused()
  }
  await page.keyboard.press('Tab')
  await expect(menu).toHaveCount(0)

  await more.click()
  await page.keyboard.press('ArrowUp')
  await expect(menu.getByTestId('menu-copy-path')).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(menu).toHaveCount(0)
  await expect(more).toBeFocused()
  const local = await lojaPath(page)
  expect(await page.evaluate(() => (window as unknown as { __copied: string[] }).__copied)).toEqual([local])
})

test('repositório em dia desliga Baixar e Enviar com o motivo', async ({ page }) => {
  await openProject(page)
  const site = repo(page, 'site')
  // The first test published `site`, so there is nothing to pull or push: the collapsed row
  // does not offer either button, and the open one shows them off, with the reason.
  await expect(site.getByTestId('repo-pull')).toHaveCount(0)
  await expect(site.getByTestId('repo-push')).toHaveCount(0)
  await ensureOpen(site)
  await expect(site.getByTestId('repo-pull')).toBeDisabled()
  await expect(site.getByTestId('repo-pull')).toHaveAttribute('title', 'Nada para baixar')
  await expect(site.getByTestId('repo-push')).toHaveAttribute('title', 'Nada para enviar')
})

/** Counts the git requests the page sends from now on; `mutating` ignores the plain reads. */
function watchGitPosts(page: Page): string[] {
  const posts: string[] = []
  page.on('request', (request) => {
    if (request.method() === 'POST' && /\/git\//.test(request.url())) posts.push(new URL(request.url()).pathname)
  })
  return posts
}

/** Leaves `loja` with one commit to send and one to pull, fetched, and returns the bare remote. */
async function divergeLoja(page: Page, file: string): Promise<{ local: string; bare: string }> {
  const loja = repo(page, 'loja')
  const local = await lojaPath(page)
  commitOnRemote(local, `${file}-remoto.md`)
  commitLocal(local, `${file}-local.md`)
  await ensureOpen(loja)
  await loja.getByTestId('repo-more').click()
  await page.getByTestId('menu-fetch').click()
  await expect(loja.getByTestId('primary-action')).toHaveText('Sincronizar 1↓ 1↑')
  return { local, bare: git(local, 'remote', 'get-url', 'origin') }
}

async function syncLoja(page: Page): Promise<void> {
  await page.getByTestId('git-view-changes').click()
  const loja = repo(page, 'loja')
  await loja.getByTestId('primary-action').click()
  await expect(loja.getByTestId('sync-counts')).toHaveText('em dia')
}

test('o ícone Baixar só baixa: faz o merge e não envia nada', async ({ page }) => {
  await openProject(page)
  const loja = repo(page, 'loja')
  const { local, bare } = await divergeLoja(page, 'icone-baixar')
  const remoteBefore = git(bare, 'rev-parse', 'main')
  const posts = watchGitPosts(page)

  await expect(loja.getByTestId('repo-pull')).toBeEnabled()
  await loja.getByTestId('repo-pull').click()
  // The merge brings the remote commit in; the local one (and the merge itself) are still to send.
  await expect(loja.getByTestId('primary-action')).toHaveText(/^Enviar 2 commits$/)
  expect(posts).toContain(`/api/projects/${new URL(page.url()).pathname.split('/')[2]}/git/pull`)
  expect(posts.filter((path) => /\/git\/(sync|push)$/.test(path))).toEqual([])
  expect(git(bare, 'rev-parse', 'main')).toBe(remoteBefore)
  await page.getByTestId('git-view-commits').click()
  const commits = page.getByTestId('commits-repo').filter({ hasText: 'loja' })
  if (await commits.getByTestId('group-outgoing').count() === 0) await commits.getByTestId('commits-repo-toggle').click()
  await expect(commits.getByTestId('group-outgoing')).toContainText('Para subir — 2 commits')
  expect(git(local, 'log', '--format=%s', 'origin/main..HEAD')).toContain('Local: icone-baixar-local.md')

  await syncLoja(page)
  expect(git(bare, 'rev-parse', 'main')).toBe(git(local, 'rev-parse', 'HEAD'))
})

test('sem alterações locais, não há composer e Ctrl+Enter não sincroniza nem envia', async ({ page }) => {
  await openProject(page)
  const loja = repo(page, 'loja')
  const { local, bare } = await divergeLoja(page, 'atalho')
  const message = loja.getByTestId('commit-message')
  const posts = watchGitPosts(page)
  const remoteBefore = git(bare, 'rev-parse', 'main')
  const headBefore = git(local, 'rev-parse', 'HEAD')

  await expect(message).toHaveCount(0)
  await page.getByTestId('git-repo-search').focus()
  await page.keyboard.press('Control+Enter')
  await expect(loja.getByTestId('primary-action')).toHaveText('Sincronizar 1↓ 1↑')

  expect(posts).toEqual([])

  // Baixar: after the pull the wide button offers Enviar; Ctrl+Enter must not push it.
  await loja.getByTestId('repo-pull').click()
  await expect(loja.getByTestId('primary-action')).toHaveText('Enviar 2 commits')
  const afterPull = posts.length
  await expect(message).toHaveCount(0)
  await page.getByTestId('git-repo-search').focus()
  await page.keyboard.press('Control+Enter')
  await expect(loja.getByTestId('primary-action')).toHaveText('Enviar 2 commits')
  expect(posts.length).toBe(afterPull)
  expect(git(bare, 'rev-parse', 'main')).toBe(remoteBefore)
  expect(git(local, 'rev-parse', 'HEAD')).not.toBe(headBefore)
  await expect(message).toHaveCount(0)
  expect(posts.filter((path) => /\/git\/(sync|push|publish)$/.test(path))).toEqual([])

  await syncLoja(page)
})

test('Ctrl+Enter ainda commita com arquivo preparado', async ({ page }) => {
  await openProject(page)
  const loja = repo(page, 'loja')
  const local = await lojaPath(page)
  writeFileSync(join(local, 'atalho-commit.md'), 'x\n')
  git(local, 'add', 'atalho-commit.md')
  await refreshRepo(page, loja)
  await ensureOpen(loja)
  await expect(loja.getByTestId('primary-action')).toHaveText('Commitar 1 preparado')
  const message = loja.getByTestId('commit-message')
  await message.fill('Commit pelo atalho')
  await message.press('Control+Enter')
  await expect(loja.getByTestId('primary-action')).toHaveText('Enviar 1 commit')
  expect(git(local, 'log', '-1', '--format=%s')).toBe('Commit pelo atalho')
  await syncLoja(page)
})

test('sem alterações: não há botão de commit, o menu libera Mesclar e a branch tem dica', async ({ page }) => {
  await openProject(page)
  const loja = repo(page, 'loja')
  await expect(loja.getByTestId('sync-counts')).toHaveText('em dia')
  await ensureOpen(loja)
  // Nothing to commit: there is no commit button, and the box says so.
  await expect(loja.getByTestId('primary-action')).toHaveCount(0)
  await expect(loja.getByTestId('no-changes')).toHaveText('Nenhuma alteração local.')
  await loja.getByTestId('repo-more').click()
  await expect(page.getByTestId('menu-merge')).toBeEnabled()
  await page.keyboard.press('Escape')
  await expect(loja.getByTestId('branch-chip')).toHaveAttribute('title', 'Trocar de branch')
})
