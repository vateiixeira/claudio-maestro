import { execFileSync } from 'node:child_process'
import { dirname, join } from 'node:path'
import { rmSync, writeFileSync } from 'node:fs'
import { expect, test } from './fixtures'

type Page = import('@playwright/test').Page

async function openProject(page: Page) {
  await page.goto('/inbox')
  const nav = page.getByRole('navigation', { name: 'Navegação' })
  // The project has no conversation, so the sidebar keeps it under "Outros projetos".
  await nav.getByRole('button', { name: /sem conversa aberta/ }).click()
  await nav.getByRole('link', { name: /Sincronia Demo/ }).first().click()
  await expect(page.getByTestId('scm-repo')).toHaveCount(2)
}

const repo = (page: Page, name: string) =>
  page.locator('[data-test="scm-repo"]').filter({ has: page.locator('[data-test="scm-repo-toggle"]', { hasText: name }) })

test.describe.configure({ mode: 'serial' })

test('sincronizar, publicar e buscar no remoto', async ({ page }) => {
  await openProject(page)
  const loja = repo(page, 'loja')
  await expect(loja.getByTestId('primary-action')).toHaveText('Sincronizar 1↓ 1↑')
  await loja.getByTestId('primary-action').click()
  await expect(loja.getByTestId('sync-counts')).toHaveText('em dia')
  await expect(loja.getByTestId('primary-action')).toHaveText('Commitar')

  const site = repo(page, 'site')
  if (await site.getByTestId('primary-action').count() === 0) await site.getByTestId('scm-repo-toggle').click()
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
  await loja.getByTestId('repo-refresh').click()
  await expect(loja.getByTestId('primary-action')).toHaveText('Enviar 1 commit')
  await expect(loja.getByTestId('repo-pull')).toBeDisabled()
  await expect(loja.getByTestId('repo-pull')).toHaveAttribute('title', 'Nada para baixar')
  const commits = page.getByTestId('commits-repo').filter({ hasText: 'loja' })
  await commits.getByTestId('commits-repo-toggle').click()
  await expect(commits.getByTestId('group-outgoing')).toContainText('Para subir — 1 commit')
  await loja.getByTestId('primary-action').click()
  await expect(loja.getByTestId('sync-counts')).toHaveText('em dia')
  await expect(commits.getByTestId('group-outgoing')).toContainText('Para subir — nenhum')
  await expect(loja.getByTestId('repo-push')).toBeDisabled()
  await expect(loja.getByTestId('repo-push')).toHaveAttribute('title', 'Nada para enviar')
})

test('baixar puro: o botão largo baixa e a seção Commits mostra o grupo Para baixar antes', async ({ page }) => {
  await openProject(page)
  const loja = repo(page, 'loja')
  commitOnRemote(await lojaPath(page), 'so-baixar.md')
  await loja.getByTestId('repo-more').click()
  await page.getByTestId('menu-fetch').click()
  await expect(loja.getByTestId('primary-action')).toHaveText('Baixar 1 commit')
  await expect(loja.getByTestId('repo-push')).toBeDisabled()
  const commits = page.getByTestId('commits-repo').filter({ hasText: 'loja' })
  await commits.getByTestId('commits-repo-toggle').click()
  await expect(commits.getByTestId('group-incoming')).toContainText('Para baixar — 1 commit')
  await loja.getByTestId('primary-action').click()
  await expect(loja.getByTestId('sync-counts')).toHaveText('em dia')
  await expect(commits.getByTestId('group-incoming')).toContainText('Para baixar — nenhum')
})

test('envio recusado: o erro aparece com o repositório recolhido, mostra a saída e fecha', async ({ page, consoleErrors }) => {
  await openProject(page)
  const loja = repo(page, 'loja')
  const local = await lojaPath(page)
  commitOnRemote(local, 'remoto-na-frente.md')
  commitLocal(local, 'local-atrasado.md')
  // Not fetched: the app still believes there is nothing to pull, so Enviar is on and git refuses.
  await loja.getByTestId('repo-refresh').click()
  await expect(loja.getByTestId('repo-push')).toBeEnabled()
  await loja.getByTestId('scm-repo-toggle').click()
  await expect(loja.getByTestId('scm-body')).toHaveCount(0)
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
  await loja.getByTestId('scm-repo-toggle').click()
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
  await expect(menu.getByRole('menuitem')).toHaveText(['Buscar no remoto', 'Copiar caminho'])
  await expect(menu.getByTestId('menu-abort')).toHaveCount(0)
  await expect(menu.getByTestId('menu-fetch')).toBeFocused()
  await page.keyboard.press('ArrowDown')
  await expect(menu.getByTestId('menu-copy-path')).toBeFocused()
  await page.keyboard.press('ArrowDown')
  await expect(menu.getByTestId('menu-fetch')).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(menu).toHaveCount(0)
  await expect(more).toBeFocused()

  await more.click()
  await page.getByTestId('repo-menu-backdrop').click({ position: { x: 5, y: 5 } })
  await expect(menu).toHaveCount(0)

  await more.click()
  // Tab walks the two items, and the next one leaves the menu.
  await page.keyboard.press('Tab')
  await expect(menu.getByTestId('menu-copy-path')).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(menu).toHaveCount(0)

  await more.click()
  await page.keyboard.press('ArrowDown')
  await page.keyboard.press('Enter')
  await expect(menu).toHaveCount(0)
  await expect(more).toBeFocused()
  const local = await lojaPath(page)
  expect(await page.evaluate(() => (window as unknown as { __copied: string[] }).__copied)).toEqual([local])
})

test('repositório em dia desliga Baixar e Enviar com o motivo', async ({ page }) => {
  await openProject(page)
  const site = repo(page, 'site')
  // The first test published `site`, so there is nothing to pull or push.
  await expect(site.getByTestId('repo-pull')).toBeDisabled()
  await expect(site.getByTestId('repo-pull')).toHaveAttribute('title', 'Nada para baixar')
  await expect(site.getByTestId('repo-push')).toHaveAttribute('title', 'Nada para enviar')
})
