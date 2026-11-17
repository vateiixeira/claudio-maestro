import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import ScmRepo from '../ScmRepo.vue'
import { useGitDetailsStore } from '../../../../stores/gitDetails'
import { useProjectsStore } from '../../../../stores/projects'
import { useSessionsStore } from '../../../../stores/sessions'
import { jsonResponse, makeProject, makeRepoDetails, makeRepoState, makeSession, routeFetch } from '../../../../test/factories'
import type { RepoDetails, RepoFile } from '../../../../types/api'

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
    expect((wrapper.get('[data-test="commit-message"]').element as HTMLInputElement).value).toBe('Meu rascunho')
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
    expect(input.attributes('placeholder')).toBe('Mensagem (Ctrl+Enter commita em main)')
    const button = wrapper.find('[data-test="primary-action"]')
    expect(button.text()).toBe('Commitar 1 preparado')
    expect(button.attributes('disabled')).toBeDefined()
    await input.setValue('Ajustar o frete')
    expect(localStorage.getItem(`maestro.commitDraft:${PATH}`)).toBe('Ajustar o frete')
    await input.trigger('keydown', { key: 'Enter', ctrlKey: true })
    await flushPromises()
    expect(bodyOf(fetchMock.mock.calls[0])).toMatchObject({ repo: PATH, message: 'Ajustar o frete' })
    expect(localStorage.getItem(`maestro.commitDraft:${PATH}`)).toBeNull()
    expect((input.element as HTMLInputElement).value).toBe('')
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
    expect((input.element as HTMLInputElement).value).toBe('Segunda mensagem')
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
