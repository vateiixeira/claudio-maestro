import { execFileSync } from 'node:child_process'
import { readFileSync, rmSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { expect, test } from './fixtures'
import type { APIRequestContext, Page } from '@playwright/test'

// These specs share the seeded repository with git-changes.e2e.ts, so each one leaves the
// repository as it found it: its own tracked file is committed and then reverted or removed.

async function repoPath(request: APIRequestContext): Promise<string> {
  const response = await request.get('/api/projects', { headers: { 'X-Maestro': '1' } })
  const projects = (await response.json()) as { name: string; path: string }[]
  return projects.find((p) => p.name === 'Alterações Demo')!.path
}

/** Commits `name` with `before`, then rewrites it with `after`, so it shows as a modified file. */
function dirtyFile(repo: string, name: string, before: string, after: string): void {
  writeFileSync(join(repo, name), before)
  const git = (...args: string[]) => execFileSync('git', ['-C', repo, '-c', 'user.name=E2E', '-c', 'user.email=e2e@example.com', ...args])
  git('add', name)
  git('commit', '-q', '-m', `Criar ${name}`)
  writeFileSync(join(repo, name), after)
}

async function openProject(page: Page) {
  await page.goto('/inbox')
  const nav = page.getByRole('navigation', { name: 'Navegação' })
  await nav.getByRole('button', { name: /sem conversa aberta/ }).click()
  await nav.getByRole('link', { name: /Alterações Demo/ }).first().click()
  const repo = page.getByTestId('scm-repo').first()
  await expect(repo).toBeVisible()
  return repo
}

const fileRow = (repo: ReturnType<Page['locator']>, path: string) => repo.locator(`[data-test="scm-file"][data-path="${path}"]`)

test('preparar e tirar da preparação, por arquivo e pelo grupo inteiro', async ({ page }) => {
  const repo = await openProject(page)
  const changes = repo.locator('[data-test="scm-group"][data-group="changes"]')
  const staged = repo.locator('[data-test="scm-group"][data-group="staged"]')
  await expect(staged).toHaveCount(0)
  const total = Number(await changes.getByTestId('scm-group-count').textContent())
  expect(total).toBeGreaterThan(0)

  // One file, and back.
  const first = changes.locator('[data-test="scm-file"]').first()
  const path = (await first.getAttribute('data-path'))!
  await first.hover()
  await first.getByTestId('file-stage').click()
  await expect(staged.getByTestId('scm-group-count')).toHaveText('1')
  const inStaged = fileRow(staged, path)
  await inStaged.hover()
  await inStaged.getByTestId('file-unstage').click()
  await expect(staged).toHaveCount(0)
  await expect(changes.getByTestId('scm-group-count')).toHaveText(String(total))

  // The whole group, and back.
  await changes.getByRole('button', { name: /Alterações/ }).hover()
  await changes.getByTestId('group-stage-all').click()
  await expect(changes).toHaveCount(0)
  await expect(staged.getByTestId('scm-group-count')).toHaveText(String(total))
  await staged.getByRole('button', { name: /Preparados/ }).hover()
  await staged.getByTestId('group-unstage-all').click()
  await expect(staged).toHaveCount(0)
  await expect(changes.getByTestId('scm-group-count')).toHaveText(String(total))
})

test('descartar um arquivo alterado: a confirmação nomeia o arquivo, cancelar não muda nada', async ({ page, request }) => {
  const repo = await repoPath(request)
  const name = 'e2e-descartar.txt'
  dirtyFile(repo, name, 'original\n', 'mudado\n')
  try {
    const scm = await openProject(page)
    const row = fileRow(scm, name)
    await row.hover()
    await row.getByTestId('file-discard').click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toContainText('Descartar alterações?')
    await expect(dialog).toContainText(name)
    await expect(dialog).not.toContainText('apaga o arquivo')

    await dialog.getByTestId('confirm-cancel').click()
    await expect(dialog).toHaveCount(0)
    await expect(row).toBeVisible()
    expect(readFileSync(join(repo, name), 'utf8')).toBe('mudado\n')

    await row.hover()
    await row.getByTestId('file-discard').click()
    await page.getByRole('dialog').getByTestId('confirm-ok').click()
    await expect(row).toHaveCount(0)
    expect(readFileSync(join(repo, name), 'utf8')).toBe('original\n')
  } finally {
    rmSync(join(repo, name), { force: true })
    execFileSync('git', ['-C', repo, '-c', 'user.name=E2E', '-c', 'user.email=e2e@example.com', 'rm', '-q', '--cached', '--ignore-unmatch', name])
    execFileSync('git', ['-C', repo, '-c', 'user.name=E2E', '-c', 'user.email=e2e@example.com', 'commit', '-q', '-m', `Remover ${name}`, '--allow-empty'])
  }
})

test('confirmação: Esc cancela, Tab fica preso, clique no texto não fecha', async ({ page, request }) => {
  const repo = await repoPath(request)
  const name = 'e2e-dialogo.txt'
  dirtyFile(repo, name, 'a\n', 'b\n')
  try {
    const scm = await openProject(page)
    const row = fileRow(scm, name)
    await row.hover()
    const trigger = row.getByTestId('file-discard')
    await trigger.focus()
    await page.keyboard.press('Enter')
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()
    const cancel = dialog.getByTestId('confirm-cancel')
    const ok = dialog.getByTestId('confirm-ok')
    await expect(cancel).toBeFocused()

    await page.keyboard.press('Tab')
    await expect(ok).toBeFocused()
    await page.keyboard.press('Tab')
    await expect(cancel).toBeFocused()
    await page.keyboard.press('Shift+Tab')
    await expect(ok).toBeFocused()

    // A click on the text sends the focus to the body; Tab must come back into the dialog and Esc must still close it.
    await dialog.getByRole('heading').click()
    await expect(dialog).toBeVisible()
    await page.keyboard.press('Tab')
    await expect(dialog.getByRole('button').first()).toBeFocused()
    await dialog.getByRole('heading').click()
    await page.keyboard.press('Escape')
    await expect(dialog).toHaveCount(0)
    expect(readFileSync(join(repo, name), 'utf8')).toBe('b\n')
  } finally {
    writeFileSync(join(repo, name), 'a\n')
    execFileSync('git', ['-C', repo, 'rm', '-q', '-f', '--ignore-unmatch', name])
    execFileSync('git', ['-C', repo, '-c', 'user.name=E2E', '-c', 'user.email=e2e@example.com', 'commit', '-q', '-m', `Remover ${name}`, '--allow-empty'])
  }
})

// The row actions stay in the layout (zero width, transparent) instead of display:none, so ConfirmDialog can
// give the focus back to the button that opened it.
test('confirmação: ao fechar, o foco volta ao botão que a abriu (só teclado)', async ({ page, request }) => {
  const repo = await repoPath(request)
  const name = 'e2e-foco.txt'
  dirtyFile(repo, name, 'a\n', 'b\n')
  try {
    const scm = await openProject(page)
    const trigger = fileRow(scm, name).getByTestId('file-discard')
    await fileRow(scm, name).getByTestId('file-open').focus()
    await page.keyboard.press('Tab')
    await page.keyboard.press('Tab')
    await expect(trigger).toBeFocused()
    await page.keyboard.press('Enter')
    await expect(page.getByRole('dialog')).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await expect(trigger).toBeFocused()
  } finally {
    execFileSync('git', ['-C', repo, 'rm', '-q', '-f', '--ignore-unmatch', name])
    execFileSync('git', ['-C', repo, '-c', 'user.name=E2E', '-c', 'user.email=e2e@example.com', 'commit', '-q', '-m', `Remover ${name}`, '--allow-empty'])
  }
})

test('o rascunho da mensagem sobrevive ao recarregar, por repositório', async ({ page }) => {
  const repo = await openProject(page)
  const message = repo.getByTestId('commit-message')
  await message.fill('Rascunho que não pode se perder')
  await page.reload()
  await expect(page.getByTestId('scm-repo').first().getByTestId('commit-message')).toHaveValue('Rascunho que não pode se perder')
  await page.getByTestId('scm-repo').first().getByTestId('commit-message').fill('')
  await page.reload()
  await expect(page.getByTestId('scm-repo').first().getByTestId('commit-message')).toHaveValue('')
})

test('descartar o grupo inteiro pede confirmação com a quantidade', async ({ page }) => {
  const repo = await openProject(page)
  const changes = repo.locator('[data-test="scm-group"][data-group="changes"]')
  const count = (await changes.getByTestId('scm-group-count').textContent())!
  await changes.getByRole('button', { name: /Alterações/ }).hover()
  await changes.getByTestId('group-discard-all').click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toContainText(Number(count) === 1 ? 'Descartar alterações?' : `Descartar ${count} alterações?`)
  await dialog.getByTestId('confirm-cancel').click()
  await expect(dialog).toHaveCount(0)
  await expect(changes.getByTestId('scm-group-count')).toHaveText(count)
})
