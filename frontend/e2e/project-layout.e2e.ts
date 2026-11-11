import { mkdirSync, realpathSync, rmSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { dirname, join, resolve } from 'node:path'
import type { APIRequestContext, Page } from '@playwright/test'
import { expect, test } from './fixtures'

async function project(request: APIRequestContext, name: string) {
  const response = await request.get('/api/projects', { headers: { 'X-Maestro': '1' } })
  const data = (await response.json() as { id: number; name: string; path: string }[]).find(item => item.name === name)!
  expect(data).toBeTruthy()
  if (name !== 'Sem projeto') expect(data.path).toContain('maestro-e2e-')
  return data
}

const conversations = (page: Page) => page.getByTestId('project-conversations')
const tab = (page: Page, name: string) => page.getByRole('tab', { name: new RegExp(`^${name}(?:\\s|$)`) })

async function scrollProjectTop(page: Page) {
  await page.getByTestId('project-pane').evaluate(element => {
    for (let node: HTMLElement | null = element; node; node = node.parentElement) node.scrollTop = 0
  })
}


test('projeto abre diretamente no Git e permite escolher Conversas explicitamente', async ({ page, request }) => {
  const data = await project(request, 'Histórico Demo')
  await page.goto(`/projects/${data.id}`)
  await expect(page.getByTestId('project-tab-git')).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByTestId('scm-repo')).toHaveCount(2)
  await expect(page.getByTestId('scm-section').getByTestId('running-session')).toHaveCount(0)
  await page.getByTestId('project-tab-conversas').click()
  await expect(page.getByTestId('project-conversations')).toBeVisible()
  expect(new URL(page.url()).searchParams.get('visao')).toBe('conversas')
  await page.reload()
  await expect(page.getByTestId('project-tab-conversas')).toHaveAttribute('aria-selected', 'true')
})

// No artificial wait: we wait for the conversation content, then drain delayed events with
// the browser's clock so an accidental deferred Git load cannot escape the assertion.
test('conversas abrem sem detalhes Git; abas permitem teclado e voltar do navegador', async ({ page, request }) => {
  const data = await project(request, 'Loja Demo')
  const gitReads: string[] = []
  page.on('request', request => {
    const url = new URL(request.url())
    if (url.pathname === `/api/projects/${data.id}/git/details` || url.pathname === `/api/projects/${data.id}/git/log`) gitReads.push(url.pathname)
  })
  await page.clock.install()
  await page.goto(`/projects/${data.id}?visao=conversas`)
  await expect(tab(page, 'Conversas')).toHaveAttribute('aria-selected', 'true')
  await expect(conversations(page).getByTestId('row-link').filter({ hasText: 'Explique a estrutura do projeto' })).toHaveCount(1)
  await page.clock.runFor(1000)
  expect(gitReads).toEqual([])
  await tab(page, 'Conversas').focus()
  await page.keyboard.press('ArrowRight')
  await expect(tab(page, 'Git')).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(tab(page, 'Git')).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByTestId('repos')).toContainText('sem repositório git')
  expect(gitReads.filter(path => path.endsWith('/details'))).toHaveLength(1)
  await tab(page, 'Organização').click()
  await expect(page.getByTestId('org-tree')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Loja Demo', exact: true, level: 1 })).toHaveCount(1)
  await page.goBack()
  await expect(tab(page, 'Git')).toHaveAttribute('aria-selected', 'true')
  await page.goBack()
  await expect(tab(page, 'Conversas')).toHaveAttribute('aria-selected', 'true')
  await expect(conversations(page)).toBeVisible()
})

test('busca e agrupador filtram uma lista única; gestão inline preserva conversas', async ({ page, request, baseURL }) => {
  const data = await project(request, 'Loja Demo')
  const groupName = 'Layout aprovado E2E'
  const renamed = 'Layout aprovado renomeado'
  let groupId: string | null = null
  try {
    await page.goto(`/projects/${data.id}?visao=conversas`)
    const list = conversations(page)
    await expect(list.getByTestId('row-link').filter({ hasText: 'Explique a estrutura do projeto' })).toHaveCount(1)
    const originalRows = await list.getByTestId('conversation-row').count()
    const hrefs = await list.getByTestId('row-link').evaluateAll(links => links.map(link => link.getAttribute('href')))
    expect(new Set(hrefs).size).toBe(hrefs.length)
    await list.getByTestId('conversation-search').fill('Explique a estrutura')
    await expect(list.getByTestId('conversation-row')).toHaveCount(1)
    await list.getByTestId('conversation-search').fill('')
    await list.getByTestId('filter-finished').click()
    await expect(list.getByTestId('filter-finished')).toHaveAttribute('aria-pressed', 'true')
    const finishedRows = await list.getByTestId('conversation-row').count()
    await list.getByTestId('filter-all').click()
    await expect(list.getByTestId('conversation-row')).toHaveCount(originalRows + finishedRows)
    await list.getByTestId('filter-open').click()
    await list.getByTestId('group-new').click()
    await list.getByTestId('group-name-input').fill(groupName)
    await list.getByTestId('group-save').click()
    const select = list.getByTestId('conversation-group-filter')
    await select.selectOption({ label: groupName })
    groupId = await select.inputValue()
    await expect(list.getByTestId('conversation-row')).toHaveCount(0)
    await list.getByTestId('group-rename').click()
    await list.getByTestId('group-name-input').fill(renamed)
    await list.getByTestId('group-save').click()
    await expect(select.getByRole('option', { name: renamed, exact: true })).toHaveCount(1)
    await list.getByTestId('group-remove').click()
    await expect(list.getByTestId('group-confirm-cancel')).toBeFocused()
    await page.keyboard.press('Escape')
    await expect(list.getByTestId('group-confirm-remove')).toHaveCount(0)
    await expect(list.getByTestId('group-remove')).toBeFocused()
    await list.getByTestId('group-remove').click()
    await list.getByTestId('group-confirm-ok').click()
    await expect(select.getByRole('option', { name: renamed, exact: true })).toHaveCount(0)
    groupId = null
    await select.selectOption('all')
    await expect(list.getByTestId('conversation-row')).toHaveCount(originalRows)
  } finally {
    if (groupId) await request.delete(`/api/groups/${groupId}`, { headers: { 'X-Maestro': '1', Origin: baseURL! } })
  }
})

test('selecionar agente e seção mantém a organização dentro do projeto', async ({ page, request }) => {
  const data = await project(request, 'Loja Demo')
  await page.goto(`/projects/${data.id}?visao=organizacao`)
  await page.getByTestId('org-node-button').filter({ hasText: 'Triagem' }).first().click()
  await expect(page.getByTestId('agent-panel').getByRole('heading', { name: 'Triagem', exact: true })).toBeVisible()
  await page.getByTestId('agent-tab-memoria').click()
  await expect(tab(page, 'Organização')).toHaveAttribute('aria-selected', 'true')
  expect(new URL(page.url()).pathname).toBe(`/projects/${data.id}`)
  expect(new URL(page.url()).searchParams.get('visao')).toBe('organizacao')
  await page.getByTestId('org-back').click()
  await expect(page.getByTestId('agent-panel')).toHaveCount(0)
  await expect(tab(page, 'Organização')).toHaveAttribute('aria-selected', 'true')
})

test('ações secundárias ficam no menu e cancelar remoção mantém o projeto', async ({ page, request }) => {
  const data = await project(request, 'Loja Demo')
  await page.goto(`/projects/${data.id}?visao=conversas`)
  const menu = page.getByTestId('project-actions')
  await menu.click()
  await page.getByTestId('rename').click()
  await expect(page.getByRole('textbox', { name: 'Nome do projeto' })).toBeFocused()
  await page.getByRole('textbox', { name: 'Nome do projeto' }).press('Escape')
  await menu.click()
  await page.getByTestId('remove').click()
  await expect(page.getByTestId('confirm-remove-cancel')).toBeFocused()
  await page.getByTestId('confirm-remove-cancel').click()
  await expect(page.getByRole('heading', { name: 'Loja Demo', exact: true, level: 1 })).toBeVisible()
  await expect(menu).toBeFocused()
})

test('layout de abas cabe em 360, 768 e 1440 px e scratch não mostra Git', async ({ page, request }) => {
  const data = await project(request, 'Loja Demo')
  const output = resolve('..', 'docs/design/2026-11-11-project-layout/implemented')
  mkdirSync(output, { recursive: true })
  await page.goto(`/projects/${data.id}?visao=conversas`)
  await expect(conversations(page).getByTestId('conversation-row').first()).toBeVisible()
  for (const width of [360, 768, 1440]) {
    await page.setViewportSize({ width, height: 1000 })
    await expect(tab(page, 'Conversas')).toBeInViewport()
    await expect(tab(page, 'Organização')).toBeInViewport()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    const bounds = (await conversations(page).boundingBox())!
    expect(bounds.x).toBeGreaterThanOrEqual(0)
    expect(bounds.x + bounds.width).toBeLessThanOrEqual(width + 1)
    await scrollProjectTop(page)
    await page.screenshot({ path: join(output, `project-conversations-${width}.png`), fullPage: true })
  }
  await tab(page, 'Organização').click()
  await expect(page.getByTestId('org-tree')).toBeVisible()
  await page.screenshot({ path: join(output, 'project-organization-1440.png'), fullPage: true })
  const git = await project(request, 'Histórico Demo')
  await page.goto(`/projects/${git.id}?visao=git`)
  await page.getByTestId('git-view-commits').click()
  await expect(page.getByTestId('commits-section')).toBeVisible()
  await expect(page.getByTestId('commits-repo')).toHaveCount(2)
  for (const theme of ['', 'dracula', 'monokai-pro']) {
    await page.evaluate(theme => {
      if (theme) document.documentElement.setAttribute('data-theme', theme)
      else document.documentElement.removeAttribute('data-theme')
    }, theme)
    await scrollProjectTop(page)
    await page.screenshot({ path: join(output, `project-git-${theme || 'maestro'}-1440.png`), fullPage: true })
  }
  await page.evaluate(() => document.documentElement.removeAttribute('data-theme'))
  const scratch = await project(request, 'Sem projeto')
  await page.goto(`/projects/${scratch.id}`)
  await expect(tab(page, 'Git')).toHaveCount(0)
  await expect(tab(page, 'Organização')).toHaveCount(0)
  await expect(page.getByTestId('project-actions')).toHaveCount(0)
})


test('organização permanece legível ao lado de uma conversa aberta', async ({ page, request }) => {
  const data = await project(request, 'Loja Demo')
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.goto(`/projects/${data.id}?visao=conversas`)
  await conversations(page).getByTestId('row-link').filter({ hasText: 'Explique a estrutura do projeto' }).click()
  await expect(page).toHaveURL(/sessao=/)
  await tab(page, 'Organização').click()
  await page.getByTestId('org-node-button').filter({ hasText: 'Triagem' }).first().click()
  await expect(page.getByTestId('agent-panel')).toBeVisible()
  await expect(page.getByTestId('org-tree')).toHaveJSProperty('tagName', 'DETAILS')
  expect((await page.getByTestId('agent-panel').boundingBox())!.width).toBeGreaterThanOrEqual(400)
  expect(new URL(page.url()).searchParams.get('sessao')).toBeTruthy()
  const pane = page.getByTestId('project-pane')
  expect(await pane.evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true)
  const output = resolve('..', 'docs/design/2026-11-11-project-layout/implemented')
  mkdirSync(output, { recursive: true })
  await page.screenshot({ path: join(output, 'project-organization-split-1440.png'), fullPage: true })
})

test('onze repositórios continuam distintos em temas e larguras diferentes', async ({ page, request }) => {
  const data = await project(request, 'Histórico Demo')
  const root = realpathSync(data.path)
  expect(root).toContain('/maestro-e2e-')
  const created: string[] = []
  const output = resolve('..', 'docs/design/2026-11-11-project-layout/implemented')
  mkdirSync(output, { recursive: true })
  try {
    for (let i = 1; i <= 9; i++) {
      const directory = join(root, `e2e-visual-${String(i).padStart(2, '0')}`)
      expect(dirname(resolve(directory))).toBe(root)
      mkdirSync(directory)
      created.push(directory)
      expect(realpathSync(directory)).toBe(directory)
      const git = (...args: string[]) => execFileSync('git', ['-C', directory, '-c', 'core.hooksPath=/dev/null', '-c', 'core.fsmonitor=false', '-c', 'user.name=E2E', '-c', 'user.email=e2e@example.invalid', ...args], { stdio: 'pipe' })
      git('init', '-b', 'main')
      git('-c', 'commit.gpgsign=false', 'commit', '--allow-empty', '-m', 'Cenário visual descartável')
    }
    await page.goto(`/projects/${data.id}?visao=git`)
    await expect(page.getByTestId('scm-repo')).toHaveCount(11)
    await page.getByTestId('git-view-commits').click()
    await expect(page.getByTestId('commits-repo')).toHaveCount(11)
    await expect(page.getByTestId('scm-section').getByTestId('running-arc')).toHaveCount(0)
    await expect(page.getByTestId('scm-section').getByTestId('running-session')).toHaveCount(0)
    const api = page.getByTestId('commits-repo').filter({ hasText: 'api' })
    await api.getByTestId('commits-repo-toggle').click()
    await expect(api.getByTestId('commit-row').first()).toBeVisible()
    await page.getByTestId('git-view-changes').click()
    for (const width of [360, 768, 1440]) {
      await page.setViewportSize({ width, height: 1000 })
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
      const repo = page.getByTestId('scm-repo').first()
      for (const [testId, label] of [['repo-pull', 'Pull'], ['repo-push', 'Push']]) {
        const action = repo.getByTestId(testId!)
        await expect(action).toHaveText(label!)
        const box = (await action.boundingBox())!
        expect(box.height).toBeGreaterThanOrEqual(32)
        expect(box.x).toBeGreaterThanOrEqual(0)
        expect(box.x + box.width).toBeLessThanOrEqual(width + 1)
      }
      for (const theme of ['', 'dracula', 'monokai-pro']) {
        await page.evaluate(theme => {
          if (theme) document.documentElement.setAttribute('data-theme', theme)
          else document.documentElement.removeAttribute('data-theme')
        }, theme)
        await scrollProjectTop(page)
    await page.screenshot({ path: join(output, `git-11-repos-${theme || 'maestro'}-${width}.png`), fullPage: true })
      }
    }
  } finally {
    for (const directory of created) {
      expect(dirname(directory)).toBe(root)
      expect(directory).toContain('/e2e-visual-')
      rmSync(directory, { recursive: true, force: true })
    }
  }
})
