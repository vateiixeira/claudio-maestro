import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, nextTick } from 'vue'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import ScmRepo from '../ScmRepo.vue'
import { useGitDetailsStore } from '../../../../stores/gitDetails'
import { useProjectsStore } from '../../../../stores/projects'
import { useSessionsStore } from '../../../../stores/sessions'
import { jsonResponse, makeLogCommit, makeProject, makeRepoDetails, makeRepoLog, makeRepoState, makeSession, routeFetch } from '../../../../test/factories'
import { useGitLogStore } from '../../../../stores/gitLog'
import type { LogCommit, RepoDetails, RepoFile } from '../../../../types/api'

enableAutoUnmount(afterEach)
const PATH = '/home/vi/dev/loja/api'
let pinia: Pinia

const file = (path: string, status: RepoFile['status'], kind: RepoFile['kind'] = 'M'): RepoFile => ({ path, status, kind, added: 3, removed: 1 })

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  useProjectsStore(pinia).projects = [makeProject({ id: 1, name: 'loja' })]
  localStorage.clear()
})
afterEach(() => vi.unstubAllGlobals())

function mountRepo(repo: RepoDetails, handlers: Record<string, () => Response | Promise<Response>> = {}) {
  useGitDetailsStore(pinia).byProject[1] = { repos: [repo], limit_reached: false }
  const fetchMock = routeFetch(handlers)
  vi.stubGlobal('fetch', fetchMock)
  const wrapper = mount(ScmRepo, { props: { projectId: 1, repo, collapseAll: 0, startOpen: true }, global: { plugins: [pinia] }, attachTo: document.body })
  return { wrapper, fetchMock }
}

const bodyOf = (call: unknown[]) => JSON.parse(String((call[1] as RequestInit).body))

describe('repositório na seção Alterações', () => {
  it('oculta o formulário e os avisos sem alterações, preservando o rascunho', async () => {
    localStorage.setItem(`maestro.commitDraft:${PATH}`, 'Meu rascunho')
    const repo = makeRepoDetails({ path: PATH, ahead: 2, state: makeRepoState({ has_hooks: true, gpgsign: true }) })
    const { wrapper } = mountRepo(repo)
    expect(wrapper.find('[data-test="commit-message"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="hooks-note"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="gpg-note"]').exists()).toBe(false)
    expect(wrapper.get('[data-test="primary-action"]').text()).toContain('Enviar')
    await wrapper.setProps({ repo: { ...repo, files: [file('a.ts', 'unstaged')] } })
    expect((wrapper.get('[data-test="commit-message"]').element as HTMLTextAreaElement).value).toBe('Meu rascunho')
  })

  it('destaca o nome da worktree mantendo o caminho completo acessível', () => {
    const { wrapper } = mountRepo(makeRepoDetails({ path: PATH, rel_path: 'angular-body/.worktrees/perf-abertura-agenda' }))
    expect(wrapper.get('[data-test="repo-short-name"]').text()).toBe('perf-abertura-agenda')
    expect(wrapper.get('[data-test="repo-parent-name"]').text()).toBe('angular-body/.worktrees')
    expect(wrapper.get('[data-test="scm-repo-toggle"]').attributes('title')).toContain('angular-body/.worktrees/perf-abertura-agenda')
  })

  it('ações de rede mostram texto e contagem além dos ícones', () => {
    const { wrapper } = mountRepo(makeRepoDetails({ path: PATH, upstream: 'origin/main', ahead: 2, behind: 1 }))
    expect(wrapper.get('[data-test="repo-pull"]').text()).toBe('Pull 1')
    expect(wrapper.get('[data-test="repo-push"]').text()).toBe('Push 2')
  })

  it.each([
    { cwd: '/home/vi/dev/loja' },
    { cwd: PATH },
    { cwd: '/home/vi/dev/loja', worktree_path: PATH },
  ])('não mostra indicador de sessão na lista Git: %j', (location) => {
    useSessionsStore(pinia).setForProject(1, [makeSession({ ...location, display_state: 'running' })])
    const { wrapper } = mountRepo(makeRepoDetails({ path: PATH }))
    expect(wrapper.find('[data-test="running-session"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="running-arc"]').exists()).toBe(false)
  })

  it('mantém o resumo das alterações e sincronização quando recolhido', async () => {
    const { wrapper } = mountRepo(makeRepoDetails({ path: PATH, changed: { staged: 2, unstaged: 3, untracked: 1 }, upstream: 'origin/main', ahead: 2, behind: 1 }))
    await wrapper.get('[data-test="scm-repo-toggle"]').trigger('click')
    expect(wrapper.find('[data-test="scm-body"]').exists()).toBe(false)
    expect(wrapper.get('[data-test="repo-changes"]').text()).toBe('6 alterações')
    expect(wrapper.get('[data-test="sync-counts"]').text()).toContain('2 para enviar')
  })

  it('agrupa em Preparados e Alterações com a letra de cada arquivo', () => {
    const { wrapper } = mountRepo(makeRepoDetails({ path: PATH, rel_path: 'api', files: [file('src/a.ts', 'staged'), file('novo.ts', 'untracked', 'A'), file('src/b.ts', 'unstaged', 'D')] }))
    const groups = wrapper.findAll('[data-test="scm-group"]')
    expect(groups.map((g) => g.find('[data-test="scm-group-title"]').text())).toEqual(['Preparados', 'Alterações'])
    expect(groups[0].find('[data-test="scm-group-count"]').text()).toBe('1')
    expect(groups[1].findAll('[data-test="scm-file"]').map((f) => f.find('[data-test="file-letter"]').text())).toEqual(['A', 'D'])
    expect(groups[0].find('[data-test="scm-file"]').text()).toContain('a.ts')
    expect(groups[0].find('[data-test="scm-file"]').text()).toContain('src')
  })

  it('prepara e tira da preparação um arquivo e o grupo', async () => {
    const repo = makeRepoDetails({ path: PATH, files: [file('a.ts', 'unstaged'), file('b.ts', 'untracked', 'A'), file('c.ts', 'staged')] })
    const { wrapper, fetchMock } = mountRepo(repo, {
      'POST /api/projects/1/git/stage': () => jsonResponse({ repo }),
      'POST /api/projects/1/git/unstage': () => jsonResponse({ repo }),
    })
    await wrapper.find('[data-test="scm-file"][data-path="a.ts"] [data-test="file-stage"]').trigger('click')
    await flushPromises()
    await wrapper.find('[data-test="scm-group"][data-group="changes"] [data-test="group-stage-all"]').trigger('click')
    await flushPromises()
    await wrapper.find('[data-test="scm-file"][data-path="c.ts"] [data-test="file-unstage"]').trigger('click')
    await flushPromises()
    expect(fetchMock.mock.calls.map((c) => [String(c[0]).split('/').pop(), bodyOf(c).paths])).toEqual([
      ['stage', ['a.ts']], ['stage', ['a.ts', 'b.ts']], ['unstage', ['c.ts']],
    ])
  })

  it('commita com o botão largo e com Ctrl+Enter, e limpa o rascunho', async () => {
    const repo = makeRepoDetails({ path: PATH, files: [file('a.ts', 'staged')] })
    const { wrapper, fetchMock } = mountRepo(repo, { 'POST /api/projects/1/git/commit': () => jsonResponse({ repo: makeRepoDetails({ path: PATH }) }) })
    const input = wrapper.find('[data-test="commit-message"]')
    expect(input.attributes('placeholder')).toBe('Mensagem do commit')
    const button = wrapper.find('[data-test="primary-action"]')
    expect(button.text()).toBe('Commitar 1 preparado')
    expect(button.attributes('disabled')).toBeDefined()
    await input.setValue('Ajustar o frete')
    expect(localStorage.getItem(`maestro.commitDraft:${PATH}`)).toBe('Ajustar o frete')
    await input.trigger('keydown', { key: 'Enter', ctrlKey: true })
    await flushPromises()
    expect(bodyOf(fetchMock.mock.calls[0])).toMatchObject({ repo: PATH, message: 'Ajustar o frete' })
    expect(localStorage.getItem(`maestro.commitDraft:${PATH}`)).toBeNull()
    expect((input.element as HTMLTextAreaElement).value).toBe('')
  })

  it('mostra o estado ocupado no botão largo e desliga os ícones', async () => {
    const repo = makeRepoDetails({ path: PATH, files: [file('a.ts', 'staged')] })
    let release!: () => void
    const { wrapper } = mountRepo(repo, { 'POST /api/projects/1/git/commit': () => new Promise<Response>((r) => { release = () => r(jsonResponse({ repo })) }) })
    await wrapper.find('[data-test="commit-message"]').setValue('x')
    await wrapper.find('[data-test="primary-action"]').trigger('click')
    await flushPromises()
    const button = wrapper.find('[data-test="primary-action"]')
    expect(button.text()).toBe('Commitando…')
    expect(button.attributes('aria-busy')).toBe('true')
    expect(wrapper.find('[data-test="branch-chip"]').attributes('disabled')).toBeDefined()
    release()
    await flushPromises()
  })

  it('erro com Ver saída do git e fechar', async () => {
    const repo = makeRepoDetails({ path: PATH, files: [file('a.ts', 'staged')] })
    const { wrapper } = mountRepo(repo, {
      'POST /api/projects/1/git/commit': () => jsonResponse({ detail: { code: 'git', message: 'Configure user.name e user.email no git para commitar.', output: 'Author identity unknown' } }, 409),
    })
    await wrapper.find('[data-test="commit-message"]').setValue('x')
    await wrapper.find('[data-test="primary-action"]').trigger('click')
    await flushPromises()
    const error = wrapper.find('[data-test="scm-error"]')
    expect(error.text()).toContain('Configure user.name e user.email')
    expect(wrapper.find('[data-test="scm-error-output"]').exists()).toBe(false)
    await error.find('[data-test="show-output"]').trigger('click')
    expect(wrapper.find('[data-test="scm-error-output"]').text()).toBe('Author identity unknown')
    await error.find('[data-test="dismiss-error"]').trigger('click')
    expect(wrapper.find('[data-test="scm-error"]').exists()).toBe(false)
    expect(localStorage.getItem(`maestro.commitDraft:${PATH}`)).toBe('x')  // kept after a failure
  })

  it('descartar pede confirmação, e arquivo novo avisa que apaga', async () => {
    const repo = makeRepoDetails({ path: PATH, files: [file('novo.ts', 'untracked', 'A')] })
    const { wrapper, fetchMock } = mountRepo(repo, { 'POST /api/projects/1/git/discard': () => jsonResponse({ repo }) })
    await wrapper.find('[data-test="scm-file"] [data-test="file-discard"]').trigger('click')
    const dialog = wrapper.find('[role="dialog"]')
    expect(dialog.text()).toContain('Descartar alterações?')
    expect(dialog.text()).toContain('Não dá para desfazer pelo app.')
    expect(dialog.text()).toContain('descartar apaga o arquivo')
    await dialog.find('[data-test="confirm-cancel"]').trigger('click')
    expect(fetchMock).not.toHaveBeenCalled()
    await wrapper.find('[data-test="scm-file"] [data-test="file-discard"]').trigger('click')
    await wrapper.find('[data-test="confirm-ok"]').trigger('click')
    await flushPromises()
    expect(bodyOf(fetchMock.mock.calls[0])).toMatchObject({ repo: PATH, paths: ['novo.ts'] })
  })

  it('descartar o grupo mostra a contagem', async () => {
    const repo = makeRepoDetails({ path: PATH, files: [file('a.ts', 'unstaged'), file('b.ts', 'unstaged')] })
    const { wrapper } = mountRepo(repo)
    await wrapper.find('[data-test="scm-group"][data-group="changes"] [data-test="group-discard-all"]').trigger('click')
    expect(wrapper.find('[role="dialog"]').text()).toContain('Descartar 2 alterações?')
  })

  it('com sessão no repositório: confirmação continua nomeando a sessão', async () => {
    useSessionsStore(pinia).setForProject(1, [makeSession({ title: 'Chatbot whatsapp', cwd: `${PATH}/src`, display_state: 'running' })])
    const repo = makeRepoDetails({ path: PATH, rel_path: 'api', files: [file('a.ts', 'unstaged')] })
    const { wrapper } = mountRepo(repo)
    expect(wrapper.find('[data-test="running-session"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="running-arc"]').exists()).toBe(false)
    await wrapper.find('[data-test="scm-file"] [data-test="file-discard"]').trigger('click')
    const dialog = wrapper.find('[role="dialog"]')
    expect(dialog.text()).toContain('Chatbot whatsapp está em execução em api.')
    expect(dialog.find('[data-test="confirm-ok"]').text()).toBe('Descartar mesmo assim')
  })

  it('commitar e preparar não perguntam nada com sessão em execução', async () => {
    useSessionsStore(pinia).setForProject(1, [makeSession({ cwd: PATH, display_state: 'running' })])
    const repo = makeRepoDetails({ path: PATH, files: [file('a.ts', 'unstaged')] })
    const { wrapper, fetchMock } = mountRepo(repo, {
      'POST /api/projects/1/git/stage': () => jsonResponse({ repo }),
      'POST /api/projects/1/git/commit': () => jsonResponse({ repo }),
    })
    await wrapper.find('[data-test="file-stage"]').trigger('click')
    await flushPromises()
    await wrapper.find('[data-test="commit-message"]').setValue('x')
    await wrapper.find('[data-test="primary-action"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('avisa de hooks e de assinatura, e repositório só leitura não tem ações', () => {
    const { wrapper } = mountRepo(makeRepoDetails({ path: PATH, files: [file('a.ts', 'unstaged')], state: makeRepoState({ has_hooks: true, gpgsign: true }) }))
    expect(wrapper.find('[data-test="hooks-note"]').text()).toBe('Este repositório tem hooks. O commit feito pelo app não os executa.')
    expect(wrapper.find('[data-test="gpg-note"]').text()).toBe('Seu git pede commits assinados. O commit feito pelo app sai sem assinatura.')
    wrapper.unmount()
    const lfs = 'Este repositório usa Git LFS. O app só mostra aqui.'
    const { wrapper: readOnly } = mountRepo(makeRepoDetails({ path: PATH, files: [file('a.psd', 'unstaged')], state: makeRepoState({ read_only: lfs }) }))
    expect(readOnly.find('[data-test="read-only-tag"]').text()).toBe('só leitura')
    expect(readOnly.find('[data-test="read-only-note"]').text()).toBe(lfs)
    expect(readOnly.find('[data-test="commit-message"]').exists()).toBe(false)
    expect(readOnly.find('[data-test="file-stage"]').exists()).toBe(false)
    expect(readOnly.find('[data-test="scm-file"]').exists()).toBe(true)
  })

  it('abre o diff do arquivo ao clicar na linha', async () => {
    const repo = makeRepoDetails({ path: PATH, rel_path: 'api', files: [file('a.ts', 'unstaged')] })
    const { wrapper } = mountRepo(repo, {
      [`GET /api/projects/1/diff?${new URLSearchParams({ repo: 'api', file: 'a.ts', scope: 'unstaged' })}`]: () => jsonResponse({ diff: '@@ -1 +1 @@\n-a\n+b\n', truncated: false }),
    })
    await wrapper.find('[data-test="scm-file"] [data-test="file-open"]').trigger('click')
    await flushPromises()
    expect(document.querySelectorAll('[data-test="scm-diff-modal"] [data-test="diff-line"]').length).toBeGreaterThan(0)
  })

  it('o que foi digitado durante o commit não some quando ele dá certo', async () => {
    const repo = makeRepoDetails({ path: PATH, files: [file('a.ts', 'staged')] })
    let release!: () => void
    const { wrapper } = mountRepo(repo, { 'POST /api/projects/1/git/commit': () => new Promise<Response>((r) => { release = () => r(jsonResponse({ repo })) }) })
    const input = wrapper.find('[data-test="commit-message"]')
    await input.setValue('Primeira')
    await wrapper.find('[data-test="primary-action"]').trigger('click')
    await flushPromises()
    await input.setValue('Segunda mensagem')
    release()
    await flushPromises()
    expect((input.element as HTMLTextAreaElement).value).toBe('Segunda mensagem')
    expect(localStorage.getItem(`maestro.commitDraft:${PATH}`)).toBe('Segunda mensagem')
  })

  it('Ctrl+Enter durante a composição de IME não commita', async () => {
    const repo = makeRepoDetails({ path: PATH, files: [file('a.ts', 'staged')] })
    const { wrapper, fetchMock } = mountRepo(repo, { 'POST /api/projects/1/git/commit': () => jsonResponse({ repo }) })
    const input = wrapper.find('[data-test="commit-message"]')
    await input.setValue('x')
    await input.trigger('keydown', { key: 'Enter', ctrlKey: true, isComposing: true })
    await flushPromises()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('sair da tela com a confirmação aberta resolve o ask com false', async () => {
    const { wrapper } = mountRepo(makeRepoDetails({ path: PATH, files: [file('a.ts', 'unstaged')] }))
    const vm = wrapper.vm as unknown as { ask: (c: unknown) => Promise<boolean> }
    const pending = vm.ask({ title: 'T', confirmLabel: 'Ok', tone: 'primary', running: null, repoName: 'api', lines: [] })
    await flushPromises()
    expect(wrapper.find('[role="dialog"]').exists()).toBe(true)
    wrapper.unmount()
    await expect(pending).resolves.toBe(false)
  })

  it('fechar a confirmação devolve o foco ao botão que a abriu', async () => {
    const repo = makeRepoDetails({ path: PATH, files: [file('a.ts', 'unstaged')] })
    const { wrapper } = mountRepo(repo)
    const trigger = wrapper.find<HTMLButtonElement>('[data-test="scm-file"] [data-test="file-discard"]')
    trigger.element.focus()
    await trigger.trigger('click')
    await flushPromises()
    expect(document.activeElement?.getAttribute('data-test')).toBe('confirm-cancel')
    await wrapper.find('[data-test="confirm-cancel"]').trigger('click')
    await flushPromises()
    expect(document.activeElement).toBe(trigger.element)
  })

  // display:none takes a button out of the focus order: when the dialog took the focus the row stopped matching
  // :focus-within, its actions vanished and the dialog had nowhere to give the focus back to on close.
  it('as ações da linha e do grupo só ficam invisíveis, nunca display:none', () => {
    const { wrapper } = mountRepo(makeRepoDetails({ path: PATH, files: [file('a.ts', 'unstaged')] }))
    for (const test of ['file-discard', 'group-discard-all']) {
      let node: Element | null = wrapper.find(`[data-test="${test}"]`).element.parentElement
      while (node && !node.className.includes('group-hover')) node = node.parentElement
      expect(node, test).not.toBeNull()
      expect(node!.classList.contains('hidden'), test).toBe(false)
      expect(node!.className, test).toContain('opacity-0')
      expect(node!.className, test).toContain('group-focus-within:opacity-100')
    }
  })
})

const closedRepo = (overrides: Partial<RepoDetails> = {}) => {
  const repo = makeRepoDetails({ path: PATH, upstream: 'origin/main', ahead: 0, behind: 0, ...overrides })
  useGitDetailsStore(pinia).byProject[1] = { repos: [repo], limit_reached: false }
  vi.stubGlobal('fetch', routeFetch({}))
  return mount(ScmRepo, { props: { projectId: 1, repo, collapseAll: 0, startOpen: false }, global: { plugins: [pinia] }, attachTo: document.body })
}

describe('linha do repositório', () => {
  it('fechado com commits para enviar: só o Push, com a contagem e o rótulo para leitor de tela', async () => {
    const wrapper = closedRepo({ ahead: 5 })
    expect(wrapper.find('[data-test="repo-pull"]').exists()).toBe(false)
    expect(wrapper.get('[data-test="repo-push"]').attributes('aria-label')).toBe('Push 5 commits')
    expect(wrapper.get('[data-test="repo-push-count"]').text()).toBe('5')
    await wrapper.setProps({ repo: makeRepoDetails({ path: PATH, upstream: 'origin/main', ahead: 1, behind: 0 }) })
    expect(wrapper.get('[data-test="repo-push"]').attributes('aria-label')).toBe('Push 1 commit')
  })

  it('fechado com commits para baixar: só o Pull, com a contagem', () => {
    const wrapper = closedRepo({ behind: 2 })
    expect(wrapper.find('[data-test="repo-push"]').exists()).toBe(false)
    expect(wrapper.get('[data-test="repo-pull"]').attributes('aria-label')).toBe('Pull 2 commits')
    expect(wrapper.get('[data-test="repo-pull-count"]').text()).toBe('2')
  })

  it('fechado e em dia: sem Pull nem Push', () => {
    const wrapper = closedRepo()
    expect(wrapper.find('[data-test="repo-pull"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="repo-push"]').exists()).toBe(false)
  })

  it('aberto e em dia: os dois existem, desligados, com o motivo e sem contagem', async () => {
    const wrapper = closedRepo()
    await wrapper.get('[data-test="scm-repo-toggle"]').trigger('click')
    for (const [test, label, title] of [['repo-pull', 'Pull', 'Nada para baixar'], ['repo-push', 'Push', 'Nada para enviar']]) {
      const button = wrapper.get(`[data-test="${test}"]`)
      expect(button.attributes('disabled'), test).toBeDefined()
      expect(button.attributes('title'), test).toBe(title)
      expect(button.attributes('aria-label'), test).toBe(label)
      expect(wrapper.find(`[data-test="${test}-count"]`).exists(), test).toBe(false)
    }
  })

  it('sem upstream e fechado, nenhum botão de rede', () => {
    const wrapper = closedRepo({ upstream: null, ahead: null, behind: null })
    expect(wrapper.find('[data-test="repo-pull"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="repo-push"]').exists()).toBe(false)
  })

  it('Merge, Commitar, Atualizar e Commits saíram da linha', async () => {
    const wrapper = closedRepo({ ahead: 1 })
    await wrapper.get('[data-test="scm-repo-toggle"]').trigger('click')
    for (const test of ['repo-merge', 'repo-commit', 'repo-refresh', 'repo-history']) {
      expect(wrapper.find(`[data-test="${test}"]`).exists(), test).toBe(false)
    }
  })

  it('a branch aparece sem o asterisco, mesmo com arquivos alterados', () => {
    const wrapper = closedRepo({ files: [file('a.ts', 'unstaged')] })
    expect(wrapper.get('[data-test="scm-branch"]').text()).toBe('main')
  })

  it('data-open acompanha abrir e fechar, e o li é um contêiner', async () => {
    const wrapper = closedRepo()
    const li = wrapper.get('[data-test="scm-repo"]')
    expect(li.classes()).toContain('@container')
    expect(li.attributes('data-open')).toBe('false')
    expect(li.classes()).not.toContain('rounded-xl')
    await wrapper.get('[data-test="scm-repo-toggle"]').trigger('click')
    expect(li.attributes('data-open')).toBe('true')
    expect(li.classes()).toContain('rounded-xl')
    expect(li.classes()).toContain('bg-panel')
    expect(li.classes()).not.toContain('odd:bg-panel')
    await wrapper.get('[data-test="scm-repo-toggle"]').trigger('click')
    expect(li.attributes('data-open')).toBe('false')
  })

  it('quiet liga data-quiet e deixa o nome em text-fg-muted, sem negrito', async () => {
    const wrapper = closedRepo()
    expect(wrapper.get('[data-test="scm-repo"]').attributes('data-quiet')).toBe('false')
    expect(wrapper.get('[data-test="repo-short-name"]').classes()).toContain('text-fg')
    await wrapper.setProps({ quiet: true })
    expect(wrapper.get('[data-test="scm-repo"]').attributes('data-quiet')).toBe('true')
    const name = wrapper.get('[data-test="repo-short-name"]')
    expect(name.classes()).toContain('text-fg-muted')
    expect(name.classes()).not.toContain('font-semibold')
  })
})

describe('menu de mais ações', () => {
  const labels = (wrapper: ReturnType<typeof closedRepo>) => wrapper.findAll('[role="menuitem"]').map((i) => [i.attributes('data-test'), i.text()])

  it('tem o rótulo "Mais ações de loja" e abre com as ações na ordem', async () => {
    const wrapper = closedRepo({ rel_path: '.' })
    const more = wrapper.get('[data-test="repo-more"]')
    expect(more.attributes('aria-label')).toBe('Mais ações de loja')
    await more.trigger('click')
    expect(labels(wrapper)).toEqual([
      ['menu-history', 'Ver commits'],
      ['menu-merge', 'Mesclar uma branch…'],
      ['menu-fetch', 'Buscar no remoto'],
      ['menu-refresh', 'Atualizar'],
      ['menu-copy-path', 'Copiar caminho'],
    ])
  })

  it('durante um merge o Abortar merge vem por último e o Mesclar fica desligado com o motivo', async () => {
    const wrapper = closedRepo({ state: makeRepoState({ merging: true, merge_branch: 'feat', conflicts: [] }) })
    await wrapper.get('[data-test="repo-more"]').trigger('click')
    expect(labels(wrapper).map((l) => l[0])).toEqual(['menu-history', 'menu-merge', 'menu-fetch', 'menu-refresh', 'menu-copy-path', 'menu-abort'])
    expect(wrapper.get('[data-test="menu-merge"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-test="menu-merge-reason"]').text()).toBe('Já há um merge em andamento')
  })

  it('o motivo do no_merge e o de repositório sem commits aparecem no Mesclar', async () => {
    const reason = 'Este repositório tem um driver de merge próprio (npm).'
    const wrapper = closedRepo({ state: makeRepoState({ no_merge: reason }) })
    await wrapper.get('[data-test="repo-more"]').trigger('click')
    expect(wrapper.get('[data-test="menu-merge"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-test="menu-merge-reason"]').text()).toBe(reason)
    wrapper.unmount()
    const empty = closedRepo({ head: null, branch: 'main', upstream: null, ahead: null, behind: null })
    await empty.get('[data-test="repo-more"]').trigger('click')
    expect(empty.get('[data-test="menu-merge"]').attributes('disabled')).toBeDefined()
    expect(empty.get('[data-test="menu-merge-reason"]').text()).toBe('Ainda não há commits.')
  })

  it('com o Mesclar ligado não mostra motivo', async () => {
    const wrapper = closedRepo()
    await wrapper.get('[data-test="repo-more"]').trigger('click')
    expect(wrapper.get('[data-test="menu-merge"]').attributes('disabled')).toBeUndefined()
    expect(wrapper.find('[data-test="menu-merge-reason"]').exists()).toBe(false)
  })

  it('Ver commits emite history e fecha o menu', async () => {
    const wrapper = closedRepo()
    await wrapper.get('[data-test="repo-more"]').trigger('click')
    await wrapper.get('[data-test="menu-history"]').trigger('click')
    expect(wrapper.emitted('history')).toHaveLength(1)
    expect(wrapper.find('[data-test="repo-menu"]').exists()).toBe(false)
  })

  it('Mesclar abre o menu de branches em modo merge; fechar sem escolher devolve o foco ao chip', async () => {
    const wrapper = closedRepo()
    await wrapper.get('[data-test="repo-more"]').trigger('click')
    await wrapper.get('[data-test="menu-merge"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-test="repo-menu"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="branch-menu"]').exists()).toBe(true)
    await wrapper.get('[data-test="branch-menu-backdrop"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-test="branch-menu"]').exists()).toBe(false)
    expect(document.activeElement).toBe(wrapper.get('[data-test="branch-chip"]').element)
  })

  it('Atualizar relê o estado do projeto e fecha o menu', async () => {
    const repo = makeRepoDetails({ path: PATH })
    useGitDetailsStore(pinia).byProject[1] = { repos: [repo], limit_reached: false }
    const fetchMock = routeFetch({ 'GET /api/projects/1/git/details': () => jsonResponse({ repos: [repo], limit_reached: false }) })
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = mount(ScmRepo, { props: { projectId: 1, repo, collapseAll: 0, startOpen: false }, global: { plugins: [pinia] }, attachTo: document.body })
    await wrapper.get('[data-test="repo-more"]').trigger('click')
    await wrapper.get('[data-test="menu-refresh"]').trigger('click')
    await flushPromises()
    expect(fetchMock.mock.calls.filter((c) => String(c[0]).includes('/git/details'))).toHaveLength(1)
    expect(wrapper.find('[data-test="repo-menu"]').exists()).toBe(false)
  })

  it('com uma ação em andamento o Atualizar fica desligado', async () => {
    const repo = makeRepoDetails({ path: PATH, upstream: 'origin/main', ahead: 0, behind: 2 })
    useGitDetailsStore(pinia).byProject[1] = { repos: [repo], limit_reached: false }
    vi.stubGlobal('fetch', routeFetch({ 'POST /api/projects/1/git/pull': () => new Promise<Response>(() => {}) }))
    const wrapper = mount(ScmRepo, { props: { projectId: 1, repo, collapseAll: 0, startOpen: true }, global: { plugins: [pinia] }, attachTo: document.body })
    await wrapper.get('[data-test="primary-action"]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-test="repo-more"]').trigger('click')
    expect(wrapper.get('[data-test="menu-refresh"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-test="menu-merge-reason"]').text()).toBe('Baixando 2 commits…')
  })
})

describe('caixa de commit', () => {
  const dirtyRepo = (overrides: Partial<RepoDetails> = {}) => makeRepoDetails({ path: '/p/loja', rel_path: 'loja', files: [file('a.ts', 'unstaged'), file('b.ts', 'unstaged')], ...overrides })

  it('o campo é um textarea com o texto de apoio e o nome acessível', () => {
    const { wrapper } = mountRepo(dirtyRepo())
    const field = wrapper.get('[data-test="commit-message"]')
    expect(field.element.tagName).toBe('TEXTAREA')
    expect(field.attributes('placeholder')).toBe('Mensagem do commit')
    expect(field.attributes('aria-label')).toBe('Mensagem do commit em loja')
  })

  it('a legenda diz em que branch o commit sai, e Merge durante um merge', () => {
    const { wrapper } = mountRepo(dirtyRepo())
    expect(wrapper.get('[data-test="commit-caption"]').text()).toBe('Commit em main')
    const merging = mountRepo(dirtyRepo({ state: makeRepoState({ merging: true, merge_branch: 'feat/x', merge_message: 'Merge x' }) }))
    expect(merging.wrapper.get('[data-test="commit-caption"]').text()).toBe('Merge em main')
    expect(merging.wrapper.get('[data-test="commit-message"]').attributes('placeholder')).toBe('Mensagem do commit do merge')
  })

  it('a dica mostra Ctrl e Enter ao commitar e some quando a ação é enviar', () => {
    const { wrapper } = mountRepo(dirtyRepo())
    expect(wrapper.findAll('[data-test="commit-hint"] kbd').map((k) => k.text())).toEqual(['Ctrl', 'Enter'])
    const push = mountRepo(makeRepoDetails({ path: '/p/loja', upstream: 'origin/main', ahead: 1 }))
    expect(push.wrapper.get('[data-test="primary-action"]').text()).toContain('Enviar')
    expect(push.wrapper.find('[data-test="commit-hint"]').exists()).toBe(false)
  })

  it('Enter sozinho quebra a linha e não commita', async () => {
    const { wrapper, fetchMock } = mountRepo(dirtyRepo(), { 'POST /api/projects/1/git/commit': () => jsonResponse({ repo: makeRepoDetails({ path: '/p/loja' }) }) })
    const field = wrapper.get('[data-test="commit-message"]')
    await field.setValue('Ajustar o frete')
    const event = new KeyboardEvent('keydown', { key: 'Enter', cancelable: true, bubbles: true })
    field.element.dispatchEvent(event)
    await flushPromises()
    expect(event.defaultPrevented).toBe(false)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('Ctrl+Enter commita e limpa o rascunho', async () => {
    const { wrapper, fetchMock } = mountRepo(dirtyRepo(), { 'POST /api/projects/1/git/commit': () => jsonResponse({ repo: makeRepoDetails({ path: '/p/loja' }) }) })
    const field = wrapper.get('[data-test="commit-message"]')
    await field.setValue('Ajustar o frete\n\nCom detalhes')
    await field.trigger('keydown', { key: 'Enter', ctrlKey: true })
    await flushPromises()
    expect(bodyOf(fetchMock.mock.calls[0])).toMatchObject({ message: 'Ajustar o frete\n\nCom detalhes' })
    expect(localStorage.getItem('maestro.commitDraft:/p/loja')).toBeNull()
  })

  it('Cmd+Enter também commita, e a composição de IME não commita', async () => {
    const { wrapper, fetchMock } = mountRepo(dirtyRepo(), { 'POST /api/projects/1/git/commit': () => jsonResponse({ repo: makeRepoDetails({ path: '/p/loja' }) }) })
    const field = wrapper.get('[data-test="commit-message"]')
    await field.setValue('x')
    await field.trigger('keydown', { key: 'Enter', metaKey: true, isComposing: true })
    expect(fetchMock).not.toHaveBeenCalled()
    await field.trigger('keydown', { key: 'Enter', metaKey: true })
    await flushPromises()
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('lê o rascunho ao abrir e grava o que se digita na mesma chave', async () => {
    localStorage.setItem('maestro.commitDraft:/p/loja', 'Ajustar o frete')
    const { wrapper } = mountRepo(dirtyRepo())
    const field = wrapper.get('[data-test="commit-message"]')
    expect((field.element as HTMLTextAreaElement).value).toBe('Ajustar o frete')
    await field.setValue('Ajustar o frete\ne o prazo')
    expect(localStorage.getItem('maestro.commitDraft:/p/loja')).toBe('Ajustar o frete\ne o prazo')
  })

  it('o botão é verde com mensagem e apagado sem ela, e conta os arquivos', async () => {
    const { wrapper } = mountRepo(dirtyRepo())
    const button = wrapper.get('[data-test="primary-action"]')
    expect(button.text()).toBe('Commitar 2 arquivos')
    expect(button.attributes('disabled')).toBeDefined()
    expect(button.classes()).not.toContain('bg-primary')
    await wrapper.get('[data-test="commit-message"]').setValue('Ajustar o frete')
    expect(button.attributes('disabled')).toBeUndefined()
    expect(button.classes()).toContain('bg-primary')
  })

  it('a caixa vem antes dos grupos de arquivos no DOM', () => {
    const { wrapper } = mountRepo(dirtyRepo())
    const box = wrapper.get('[data-test="scm-commit-box"]').element
    const group = wrapper.get('[data-test="scm-group"]').element
    expect(box.compareDocumentPosition(group) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('o corpo é um contêiner e as colunas dependem da largura dele, não da janela', () => {
    const { wrapper } = mountRepo(dirtyRepo())
    expect(wrapper.get('[data-test="scm-body"]').html()).toContain('@3xl:grid-cols-')
    expect(wrapper.get('[data-test="scm-body"]').html()).not.toMatch(/(?:^|[\s"])(?:md|lg|xl):/)
  })

  it('sem alterações a caixa só traz o botão, ou o aviso de que não há nada', () => {
    const none = mountRepo(makeRepoDetails({ path: '/p/loja' }))
    expect(none.wrapper.get('[data-test="scm-commit-box"]').text()).toContain('Nenhuma alteração local.')
    expect(none.wrapper.find('[data-test="commit-message"]').exists()).toBe(false)
    expect(none.wrapper.find('[data-test="commit-caption"]').exists()).toBe(false)
    const pull = mountRepo(makeRepoDetails({ path: '/p/loja', upstream: 'origin/main', behind: 1 }))
    expect(pull.wrapper.get('[data-test="scm-commit-box"] [data-test="primary-action"]').text()).toContain('Baixar')
  })
})

describe('Para enviar', () => {
  const HEAD = 'abc1234abc1234abc1234abc1234abc1234abc12'
  const UPSTREAM = 'def5678def5678def5678def5678def5678def56'
  const outgoingCommits = (n: number, from = 0): LogCommit[] => Array.from({ length: n }, (_, i) => makeLogCommit({
    full_hash: `${(from + i).toString(16).padStart(2, '0')}${'0'.repeat(38)}`, subject: `Mudança ${from + i}`, pushed: false,
  }))
  const base = { path: '/p/loja', upstream: 'origin/main' }

  /** The details endpoint sends no commits (`include_commits=False`): the list comes from the history API. */
  function logFetch(options: { outgoing?: () => Response | Promise<Response>; head?: () => string } = {}) {
    return vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method && init.method !== 'GET') return jsonResponse({ detail: 'Sem resposta falsa' }, 599)
      const query = new URL(url, 'http://localhost').searchParams
      const head = options.head?.() ?? HEAD
      if (query.get('direction') === 'outgoing') return options.outgoing ? options.outgoing() : jsonResponse(makeRepoLog({ direction: 'outgoing', head_sha: head, upstream_sha: UPSTREAM, commits: [], outgoing_count: 0 }))
      return jsonResponse(makeRepoLog({ head_sha: head, upstream_sha: UPSTREAM, commits: [], outgoing_count: 0 }))
    })
  }
  function mountOutgoing(repo: RepoDetails, fetchMock = logFetch(), startOpen = true) {
    useGitDetailsStore(pinia).byProject[1] = { repos: [repo], limit_reached: false }
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = mount(ScmRepo, { props: { projectId: 1, repo, collapseAll: 0, startOpen }, global: { plugins: [pinia] }, attachTo: document.body })
    return { wrapper, fetchMock }
  }
  const outgoingCalls = (fetchMock: ReturnType<typeof logFetch>) => fetchMock.mock.calls.filter((c) => String(c[0]).includes('direction=outgoing'))
  const respondWith = (commits: LogCommit[], total: number) => () => jsonResponse(makeRepoLog({ direction: 'outgoing', head_sha: HEAD, upstream_sha: UPSTREAM, commits, outgoing_count: total }))

  it('lista os commits que o Push leva, vindos do histórico, com o total', async () => {
    const { wrapper, fetchMock } = mountOutgoing(makeRepoDetails({ ...base, ahead: 2 }), logFetch({ outgoing: respondWith(outgoingCommits(2), 2) }))
    await flushPromises()
    const section = wrapper.get('[data-test="scm-outgoing"]')
    expect(section.text()).toContain('Para enviar')
    expect(section.text()).toContain('o que o Push leva para o remoto')
    expect(wrapper.get('[data-test="scm-outgoing-count"]').text()).toBe('2')
    const rows = wrapper.findAll('[data-test="scm-outgoing-commit"]')
    expect(rows).toHaveLength(2)
    expect(rows[0].text()).toContain('0000000')
    expect(rows[0].text()).toContain('Mudança 0')
    expect(rows[1].text()).toContain('Mudança 1')
    expect(wrapper.find('[data-test="scm-outgoing-more"]').exists()).toBe(false)
    expect(outgoingCalls(fetchMock)).toHaveLength(1)
  })

  it('não usa os commits do endpoint de detalhes', async () => {
    const stale = [{ hash: 'f000000', full_hash: 'f'.repeat(40), subject: 'Do detalhe', author: 'x', date: '2026-09-30T12:00:00-03:00', pushed: false }]
    const { wrapper } = mountOutgoing(makeRepoDetails({ ...base, ahead: 1, commits: stale }), logFetch({ outgoing: respondWith(outgoingCommits(1), 1) }))
    await flushPromises()
    expect(wrapper.get('[data-test="scm-outgoing"]').text()).not.toContain('Do detalhe')
    expect(wrapper.get('[data-test="scm-outgoing-commit"]').text()).toContain('Mudança 0')
  })

  it('mostra no máximo 10 commits e diz quantos faltam, abrindo o histórico', async () => {
    const { wrapper } = mountOutgoing(makeRepoDetails({ ...base, ahead: 42 }), logFetch({ outgoing: respondWith(outgoingCommits(30), 42) }))
    await flushPromises()
    expect(wrapper.get('[data-test="scm-outgoing-count"]').text()).toBe('42')
    expect(wrapper.findAll('[data-test="scm-outgoing-commit"]')).toHaveLength(10)
    const more = wrapper.get('[data-test="scm-outgoing-more"]')
    expect(more.text()).toBe('e mais 32 no histórico')
    await more.trigger('click')
    expect(wrapper.emitted('history')).toHaveLength(1)
  })

  it('não carrega nem aparece sem nada a enviar, sem upstream, com o HEAD solto ou só leitura', async () => {
    const cases: RepoDetails[] = [
      makeRepoDetails({ ...base, ahead: 0 }),
      makeRepoDetails({ path: '/p/loja', upstream: null, ahead: 3 }),
      makeRepoDetails({ ...base, upstream: null, detached: true, branch: null, head: 'abc1234', ahead: 2 }),
      makeRepoDetails({ ...base, ahead: 2, state: makeRepoState({ read_only: 'Repositório em modo só leitura.' }) }),
    ]
    for (const repo of cases) {
      const { wrapper, fetchMock } = mountOutgoing(repo)
      await flushPromises()
      expect(wrapper.find('[data-test="scm-outgoing"]').exists()).toBe(false)
      expect(fetchMock.mock.calls.filter((c) => String(c[0]).includes('/git/log'))).toHaveLength(0)
      wrapper.unmount()
    }
  })

  it('com o corpo fechado não pede nada, e abre carregando', async () => {
    const { wrapper, fetchMock } = mountOutgoing(makeRepoDetails({ ...base, ahead: 1 }), logFetch({ outgoing: respondWith(outgoingCommits(1), 1) }), false)
    await flushPromises()
    expect(fetchMock).not.toHaveBeenCalled()
    await wrapper.get('[data-test="scm-repo-toggle"]').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('[data-test="scm-outgoing-commit"]')).toHaveLength(1)
  })

  it('mostra Carregando… enquanto a lista não chegou', async () => {
    let release: (r: Response) => void = () => {}
    const { wrapper } = mountOutgoing(makeRepoDetails({ ...base, ahead: 3 }), logFetch({ outgoing: () => new Promise<Response>((resolve) => { release = resolve }) }))
    await flushPromises()
    const loading = wrapper.get('[data-test="scm-outgoing-loading"]')
    expect(loading.text()).toBe('Carregando…')
    expect(loading.classes()).toContain('text-fg-muted')
    expect(wrapper.get('[data-test="scm-outgoing-count"]').text()).toBe('3')
    release(respondWith(outgoingCommits(3), 3)())
    await flushPromises()
    expect(wrapper.find('[data-test="scm-outgoing-loading"]').exists()).toBe(false)
    expect(wrapper.findAll('[data-test="scm-outgoing-commit"]')).toHaveLength(3)
  })

  it('com falha mostra o erro e Tentar novamente carrega de novo', async () => {
    let fail = true
    const { wrapper, fetchMock } = mountOutgoing(makeRepoDetails({ ...base, ahead: 1 }), logFetch({
      outgoing: () => (fail ? jsonResponse({ detail: 'Não foi possível consultar o Git.' }, 502) : respondWith(outgoingCommits(1), 1)()),
    }))
    await flushPromises()
    const error = wrapper.get('[data-test="scm-outgoing-error"]')
    expect(error.text()).toContain('Não foi possível consultar o Git.')
    expect(error.classes()).toContain('text-diff-del-fg')
    fail = false
    await wrapper.get('[data-test="scm-outgoing-retry"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-test="scm-outgoing-error"]').exists()).toBe(false)
    expect(wrapper.findAll('[data-test="scm-outgoing-commit"]')).toHaveLength(1)
    expect(outgoingCalls(fetchMock)).toHaveLength(2)
  })

  it('depois de um commit (HEAD e ahead mudam) descarta a lista e carrega de novo', async () => {
    let head = HEAD
    let answer = respondWith(outgoingCommits(1), 1)
    const { wrapper, fetchMock } = mountOutgoing(makeRepoDetails({ ...base, ahead: 1 }), logFetch({ head: () => head, outgoing: () => answer() }))
    await flushPromises()
    expect(wrapper.findAll('[data-test="scm-outgoing-commit"]')).toHaveLength(1)
    head = 'e'.repeat(40)
    answer = () => jsonResponse(makeRepoLog({ direction: 'outgoing', head_sha: head, upstream_sha: UPSTREAM, commits: outgoingCommits(2), outgoing_count: 2 }))
    await wrapper.setProps({ repo: makeRepoDetails({ ...base, ahead: 2, head_sha: head }) })
    await flushPromises()
    expect(wrapper.get('[data-test="scm-outgoing-count"]').text()).toBe('2')
    expect(wrapper.findAll('[data-test="scm-outgoing-commit"]')).toHaveLength(2)
    expect(outgoingCalls(fetchMock)).toHaveLength(2)
  })

  it('depois de um push a seção some, e um commit novo carrega só o que falta enviar', async () => {
    let head = HEAD
    const { wrapper, fetchMock } = mountOutgoing(makeRepoDetails({ ...base, ahead: 1 }), logFetch({ head: () => head, outgoing: () => jsonResponse(makeRepoLog({ direction: 'outgoing', head_sha: head, upstream_sha: UPSTREAM, commits: outgoingCommits(1, 7), outgoing_count: 1 })) }))
    await flushPromises()
    await wrapper.setProps({ repo: makeRepoDetails({ ...base, ahead: 0 }) })
    await flushPromises()
    expect(wrapper.find('[data-test="scm-outgoing"]').exists()).toBe(false)
    head = 'e'.repeat(40)
    await wrapper.setProps({ repo: makeRepoDetails({ ...base, ahead: 1, head_sha: head }) })
    await flushPromises()
    expect(wrapper.findAll('[data-test="scm-outgoing-commit"]')).toHaveLength(1)
    expect(outgoingCalls(fetchMock)).toHaveLength(2)
    expect(useGitLogStore(pinia).logFor(1, '/p/loja', 'outgoing')).toBeNull()
  })

  it('lê o HEAD direto da API: sem ref, sem snapshot e com limite de 10', async () => {
    const { fetchMock } = mountOutgoing(makeRepoDetails({ ...base, ahead: 2 }), logFetch({ outgoing: respondWith(outgoingCommits(2), 2) }))
    await flushPromises()
    const params = new URL(String(outgoingCalls(fetchMock)[0][0]), 'http://localhost').searchParams
    expect(params.get('direction')).toBe('outgoing')
    expect(params.get('limit')).toBe('10')
    expect(params.has('ref')).toBe(false)
    expect(params.has('snapshot_head')).toBe(false)
    expect(fetchMock.mock.calls.filter((c) => String(c[0]).includes('/git/log'))).toHaveLength(1)
  })

  it('a branch escolhida na aba Commits não muda o que o Para enviar mostra, e a loja não é tocada', async () => {
    const store = useGitLogStore(pinia)
    store.logs['1:/p/loja:all'] = { ref: 'refs/heads/outra', branch: 'outra', upstream: null, headSha: 'f'.repeat(40), upstreamSha: null, commits: outgoingCommits(60, 100), incoming: [], incomingCount: 0, outgoingCount: 0, nextSkip: 30, hasMore: true, loading: false, error: null, updateAvailable: false }
    const before = JSON.stringify(store.logs)
    const { wrapper, fetchMock } = mountOutgoing(makeRepoDetails({ ...base, ahead: 1 }), logFetch({ outgoing: respondWith(outgoingCommits(1), 1) }))
    await flushPromises()
    expect(wrapper.get('[data-test="scm-outgoing-commit"]').text()).toContain('Mudança 0')
    expect(new URL(String(outgoingCalls(fetchMock)[0][0]), 'http://localhost').searchParams.has('ref')).toBe(false)
    expect(JSON.stringify(store.logs)).toBe(before)
  })

  it('uma mudança de HEAD não altera o estado da loja do histórico', async () => {
    const store = useGitLogStore(pinia)
    const reading = { ref: null, branch: 'main', upstream: 'origin/main', headSha: HEAD, upstreamSha: UPSTREAM, commits: outgoingCommits(60, 100), incoming: [], incomingCount: 0, outgoingCount: 1, nextSkip: 60, hasMore: true, loading: false, error: null, updateAvailable: false }
    store.logs['1:/p/loja:all'] = reading
    const snapshot = JSON.stringify(store.logs)
    const { wrapper } = mountOutgoing(makeRepoDetails({ ...base, ahead: 1 }), logFetch({ outgoing: respondWith(outgoingCommits(1), 1) }))
    await flushPromises()
    await wrapper.setProps({ repo: makeRepoDetails({ ...base, ahead: 2, head_sha: 'e'.repeat(40) }) })
    await flushPromises()
    expect(JSON.stringify(store.logs)).toBe(snapshot)
    expect(store.logFor(1, '/p/loja')!.commits).toHaveLength(60)
    expect(Object.keys(store.logs)).toEqual(['1:/p/loja:all'])
  })

  it('uma resposta antiga que chega depois da nova é ignorada', async () => {
    const pending: Array<(r: Response) => void> = []
    const { wrapper } = mountOutgoing(makeRepoDetails({ ...base, ahead: 1 }), logFetch({ outgoing: () => new Promise<Response>((resolve) => { pending.push(resolve) }) }))
    await flushPromises()
    await wrapper.setProps({ repo: makeRepoDetails({ ...base, ahead: 2, head_sha: 'e'.repeat(40) }) })
    await flushPromises()
    expect(pending).toHaveLength(2)
    pending[1](respondWith(outgoingCommits(2, 50), 2)())
    await flushPromises()
    pending[0](respondWith(outgoingCommits(1, 9), 1)())
    await flushPromises()
    expect(wrapper.findAll('[data-test="scm-outgoing-commit"]').map((r) => r.text())).toEqual([expect.stringContaining('Mudança 50'), expect.stringContaining('Mudança 51')])
  })

  it('cancela a leitura anterior ao reler e ao desmontar', async () => {
    const signals: AbortSignal[] = []
    const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
      signals.push(init!.signal!)
      return new Promise<Response>(() => {})
    })
    const { wrapper } = mountOutgoing(makeRepoDetails({ ...base, ahead: 1 }), fetchMock as unknown as ReturnType<typeof logFetch>)
    await flushPromises()
    await wrapper.setProps({ repo: makeRepoDetails({ ...base, ahead: 2, head_sha: 'e'.repeat(40) }) })
    await flushPromises()
    expect(signals).toHaveLength(2)
    expect(signals[0].aborted).toBe(true)
    expect(signals[1].aborted).toBe(false)
    wrapper.unmount()
    expect(signals[1].aborted).toBe(true)
  })

  it('fechar o corpo cancela a leitura e abrir lê de novo', async () => {
    const { wrapper, fetchMock } = mountOutgoing(makeRepoDetails({ ...base, ahead: 1 }), logFetch({ outgoing: respondWith(outgoingCommits(1), 1) }))
    await flushPromises()
    await wrapper.get('[data-test="scm-repo-toggle"]').trigger('click')
    expect(wrapper.find('[data-test="scm-outgoing"]').exists()).toBe(false)
    await wrapper.get('[data-test="scm-repo-toggle"]').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('[data-test="scm-outgoing-commit"]')).toHaveLength(1)
    expect(outgoingCalls(fetchMock)).toHaveLength(2)
  })

  it('fica junto dos arquivos, depois dos grupos', async () => {
    const { wrapper } = mountOutgoing(makeRepoDetails({ ...base, ahead: 1, files: [file('a.ts', 'unstaged')] }), logFetch({ outgoing: respondWith(outgoingCommits(1), 1) }))
    await flushPromises()
    const group = wrapper.get('[data-test="scm-group"]').element
    expect(group.compareDocumentPosition(wrapper.get('[data-test="scm-outgoing"]').element) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })
})

describe('foco depois de Push e Pull pela linha fechada', () => {
  /** The repository comes from the store, as in the app: the answer of the action re-renders the row. */
  function mountFromStore(repo: RepoDetails, handlers: Record<string, () => Response | Promise<Response>>) {
    useGitDetailsStore(pinia).byProject[1] = { repos: [repo], limit_reached: false }
    vi.stubGlobal('fetch', routeFetch(handlers))
    const details = useGitDetailsStore(pinia)
    const Harness = defineComponent({ render: () => h(ScmRepo, { projectId: 1, repo: details.reposFor(1)[0], collapseAll: 0, startOpen: false }) })
    return mount(Harness, { global: { plugins: [pinia] }, attachTo: document.body })
  }
  const toggleOf = (path: string) => [...document.querySelectorAll<HTMLElement>('[data-test="scm-repo"]')].find((el) => el.dataset.repo === path)?.querySelector('[data-test="scm-repo-toggle"]')

  it.each([
    ['repo-push', { upstream: 'origin/main', ahead: 2, behind: 0 }, 'push'],
    ['repo-pull', { upstream: 'origin/main', ahead: 0, behind: 2 }, 'pull'],
  ])('%s: o botão some e o foco vai para o nome do repositório', async (test, state, kind) => {
    const repo = makeRepoDetails({ path: PATH, ...state })
    const wrapper = mountFromStore(repo, { [`POST /api/projects/1/git/${kind}`]: () => jsonResponse({ repo: makeRepoDetails({ path: PATH, upstream: 'origin/main', ahead: 0, behind: 0 }), conflicts: false }) })
    const button = wrapper.get(`[data-test="${test}"]`)
    ;(button.element as HTMLElement).focus()
    expect(document.activeElement).toBe(button.element)
    await button.trigger('click')
    await flushPromises()
    expect(wrapper.find(`[data-test="${test}"]`).exists()).toBe(false)
    expect(document.activeElement).toBe(toggleOf(PATH))
    expect(document.activeElement).toBe(wrapper.get('[data-test="scm-repo-toggle"]').element)
  })

  it('não rouba o foco de quem estava em outro lugar', async () => {
    const repo = makeRepoDetails({ path: PATH, upstream: 'origin/main', ahead: 2, behind: 0 })
    const wrapper = mountFromStore(repo, { 'POST /api/projects/1/git/push': () => jsonResponse({ repo: makeRepoDetails({ path: PATH, upstream: 'origin/main', ahead: 0, behind: 0 }) }) })
    const other = document.createElement('input')
    document.body.appendChild(other)
    other.focus()
    await wrapper.get('[data-test="repo-push"]').trigger('click')
    await flushPromises()
    expect(document.activeElement).toBe(other)
    other.remove()
  })

  it('com a falha o botão fica e o foco não é movido', async () => {
    const repo = makeRepoDetails({ path: PATH, upstream: 'origin/main', ahead: 2, behind: 0 })
    const wrapper = mountFromStore(repo, { 'POST /api/projects/1/git/push': () => jsonResponse({ detail: { code: 'git', message: 'Recusado.', output: '' } }, 409) })
    const button = wrapper.get('[data-test="repo-push"]')
    ;(button.element as HTMLElement).focus()
    await button.trigger('click')
    await flushPromises()
    await nextTick()
    expect(document.activeElement).toBe(wrapper.get('[data-test="repo-push"]').element)
  })
})

describe('cabeçalho aberto', () => {
  it('usa card, onde os textos de cor passam de 4,5:1 nos oito temas', () => {
    const { wrapper } = mountRepo(makeRepoDetails({ path: PATH }))
    const header = wrapper.get('[data-test="scm-repo-toggle"]').element.parentElement!
    expect(header.className).toContain('bg-card')
    expect(header.className).not.toContain('bg-elevated')
  })

  it('Pull, Push e Mais ações têm um hover que se vê sobre o cabeçalho (elevated, mais claro que card)', () => {
    const { wrapper } = mountRepo(makeRepoDetails({ path: PATH, upstream: 'origin/main', ahead: 1, behind: 1 }))
    for (const test of ['repo-pull', 'repo-push', 'repo-more']) {
      const classes = wrapper.get(`[data-test="${test}"]`).classes()
      expect(classes, test).toContain('hover:bg-elevated')
      expect(classes, test).not.toContain('hover:bg-card')
    }
    expect(wrapper.get('[data-test="repo-push"]').classes()).toContain('hover:border-fg-muted')
  })
})

describe('dica do atalho de commit', () => {
  const dirty = (overrides: Partial<RepoDetails> = {}) => makeRepoDetails({ path: '/p/loja', rel_path: 'loja', files: [file('a.ts', 'unstaged')], ...overrides })
  afterEach(() => vi.restoreAllMocks())

  it('o título diz "faz o commit" e o campo aponta a dica e o atalho', () => {
    const { wrapper } = mountRepo(dirty())
    const hint = wrapper.get('[data-test="commit-hint"]')
    expect(hint.attributes('title')).toBe('Ctrl+Enter faz o commit')
    expect(hint.attributes('id')).toBeTruthy()
    const field = wrapper.get('[data-test="commit-message"]')
    expect(field.attributes('aria-describedby')).toBe(hint.attributes('id'))
    expect(field.attributes('aria-keyshortcuts')).toBe('Control+Enter')
  })

  it('no Mac a dica mostra Cmd como texto e o atalho é Meta+Enter', () => {
    vi.spyOn(navigator, 'platform', 'get').mockReturnValue('MacIntel')
    const { wrapper } = mountRepo(dirty())
    expect(wrapper.findAll('[data-test="commit-hint"] kbd').map((k) => k.text())).toEqual(['Cmd', 'Enter'])
    expect(wrapper.get('[data-test="commit-hint"]').attributes('title')).toBe('Cmd+Enter faz o commit')
    expect(wrapper.get('[data-test="commit-message"]').attributes('aria-keyshortcuts')).toBe('Meta+Enter')
  })

  it('só aparece com o campo de mensagem: repositório limpo ocupado não mostra a dica', async () => {
    const repo = makeRepoDetails({ path: '/p/loja', upstream: 'origin/main', ahead: 0, behind: 0 })
    useGitDetailsStore(pinia).byProject[1] = { repos: [repo], limit_reached: false }
    vi.stubGlobal('fetch', routeFetch({ 'POST /api/projects/1/git/fetch-repo': () => new Promise<Response>(() => {}) }))
    const wrapper = mount(ScmRepo, { props: { projectId: 1, repo, collapseAll: 0, startOpen: true }, global: { plugins: [pinia] }, attachTo: document.body })
    expect(wrapper.find('[data-test="commit-message"]').exists()).toBe(false)
    await wrapper.get('[data-test="repo-more"]').trigger('click')
    await wrapper.get('[data-test="menu-fetch"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-test="commit-hint"]').exists()).toBe(false)
  })

  it('durante um merge a dica aparece junto do campo', () => {
    const { wrapper } = mountRepo(dirty({ files: [], state: makeRepoState({ merging: true, merge_branch: 'feat/x', merge_message: 'Merge x' }) }))
    expect(wrapper.find('[data-test="commit-message"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="commit-hint"]').exists()).toBe(true)
  })
})

describe('motivo do Mesclar desligado', () => {
  it('o item do menu é ligado ao motivo por aria-describedby', async () => {
    const { wrapper } = mountRepo(makeRepoDetails({ path: PATH, head: null, branch: 'main', upstream: null, ahead: null, behind: null }))
    await wrapper.get('[data-test="repo-more"]').trigger('click')
    const reason = wrapper.get('[data-test="menu-merge-reason"]')
    expect(reason.attributes('id')).toBeTruthy()
    expect(wrapper.get('[data-test="menu-merge"]').attributes('aria-describedby')).toBe(reason.attributes('id'))
  })

  it('sem motivo não há aria-describedby', async () => {
    const { wrapper } = mountRepo(makeRepoDetails({ path: PATH }))
    await wrapper.get('[data-test="repo-more"]').trigger('click')
    expect(wrapper.find('[data-test="menu-merge-reason"]').exists()).toBe(false)
    expect(wrapper.get('[data-test="menu-merge"]').attributes('aria-describedby')).toBeUndefined()
  })
})
