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
    expect(bodyOf(fetchMock.mock.calls[0])).toEqual({ repo: PATH, message: 'Ajustar o frete' })
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
    expect(wrapper.find('[data-test="repo-commit"]').attributes('disabled')).toBeDefined()
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
    expect(bodyOf(fetchMock.mock.calls[0])).toEqual({ repo: PATH, paths: ['novo.ts'] })
  })

  it('descartar o grupo mostra a contagem', async () => {
    const repo = makeRepoDetails({ path: PATH, files: [file('a.ts', 'unstaged'), file('b.ts', 'unstaged')] })
    const { wrapper } = mountRepo(repo)
    await wrapper.find('[data-test="scm-group"][data-group="changes"] [data-test="group-discard-all"]').trigger('click')
    expect(wrapper.find('[role="dialog"]').text()).toContain('Descartar 2 alterações?')
  })

  it('com sessão em execução no repositório: arco na linha e confirmação nomeando a sessão', async () => {
    useSessionsStore(pinia).setForProject(1, [makeSession({ title: 'Chatbot whatsapp', cwd: `${PATH}/src`, display_state: 'running' })])
    const repo = makeRepoDetails({ path: PATH, rel_path: 'api', files: [file('a.ts', 'unstaged')] })
    const { wrapper } = mountRepo(repo)
    expect(wrapper.find('[data-test="running-arc"]').attributes('title')).toBe('Chatbot whatsapp em execução aqui')
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
      [`GET /api/projects/1/diff?${new URLSearchParams({ repo: 'api', file: 'a.ts' })}`]: () => jsonResponse({ diff: '@@ -1 +1 @@\n-a\n+b\n', truncated: false }),
    })
    await wrapper.find('[data-test="scm-file"] [data-test="file-open"]').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('[data-test="diff-line"]').length).toBeGreaterThan(0)
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
