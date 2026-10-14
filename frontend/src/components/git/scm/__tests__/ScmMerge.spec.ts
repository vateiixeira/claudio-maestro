import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'
import ScmRepo from '../ScmRepo.vue'
import { useGitDetailsStore } from '../../../../stores/gitDetails'
import { useProjectsStore } from '../../../../stores/projects'
import { useSessionsStore } from '../../../../stores/sessions'
import { jsonResponse, makeProject, makeRepoDetails, makeRepoState, makeSession, routeFetch } from '../../../../test/factories'
import type { BranchList, RepoDetails, RepoFile } from '../../../../types/api'

enableAutoUnmount(afterEach)
const PATH = '/home/vi/dev/crm/api'
const BRANCHES = `GET /api/projects/1/git/branches?${new URLSearchParams({ repo: PATH })}`
const LIST: BranchList = {
  current: 'refs/heads/develop',
  local: [
    { name: 'develop', ref: 'refs/heads/develop', sha: 'a1', date: '2026-10-13T10:00:00-03:00', upstream: null },
    { name: 'feat/agente', ref: 'refs/heads/feat/agente', sha: 'b2', date: '2026-10-12T10:00:00-03:00', upstream: null },
  ],
  remote: [],
}
let pinia: Pinia
let router: Router

const conflict = (path: string): RepoFile => ({ path, status: 'conflict', kind: 'U', added: null, removed: null })
const staged = (path: string): RepoFile => ({ path, status: 'staged', kind: 'M', added: 1, removed: 0 })
const merging = (conflicts: string[], files: RepoFile[]) => makeRepoDetails({
  path: PATH, rel_path: 'api', branch: 'develop', files,
  state: makeRepoState({ merging: true, merge_branch: 'feat/agente', merge_message: "Merge branch 'feat/agente' into develop", conflicts }),
})

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  useProjectsStore(pinia).projects = [makeProject({ id: 1, name: 'crm' })]
  localStorage.clear()
  router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/', component: { template: '<div />' } },
    { path: '/projects/:id', name: 'project', component: { template: '<div />' } },
    { path: '/sessions/:id', name: 'session', component: { template: '<div />' } },
  ] })
})
afterEach(() => vi.unstubAllGlobals())

function mountRepo(repo: RepoDetails, handlers: Record<string, (init?: RequestInit) => Response | Promise<Response>> = {}) {
  useGitDetailsStore(pinia).byProject[1] = { repos: [repo], limit_reached: false }
  const fetchMock = routeFetch({ [BRANCHES]: () => jsonResponse(LIST), ...handlers })
  vi.stubGlobal('fetch', fetchMock)
  const wrapper = mount(ScmRepo, { props: { projectId: 1, repo, collapseAll: 0, startOpen: true }, global: { plugins: [pinia, router] }, attachTo: document.body })
  return { wrapper, fetchMock }
}
const posts = (fetchMock: ReturnType<typeof routeFetch>) =>
  fetchMock.mock.calls
    .filter((c) => (c[1] as RequestInit | undefined)?.method === 'POST')
    .map((c) => {
      const body = (c[1] as RequestInit).body
      return [String(c[0]).split('/git/').pop(), body ? JSON.parse(String(body)) : null]
    })

describe('branches e merge no repositório', () => {
  it('clicar na branch abre o menu e escolher troca, sem perguntar', async () => {
    const repo = makeRepoDetails({ path: PATH, branch: 'develop' })
    const { wrapper, fetchMock } = mountRepo(repo, { 'POST /api/projects/1/git/switch': () => jsonResponse({ repo: makeRepoDetails({ path: PATH, branch: 'feat/agente' }) }) })
    await wrapper.find('[data-test="branch-chip"]').trigger('click')
    await flushPromises()
    await wrapper.find('[data-name="feat/agente"]').trigger('click')
    await flushPromises()
    expect(posts(fetchMock)).toEqual([['switch', { repo: PATH, ref: 'refs/heads/feat/agente' }]])
    expect(wrapper.find('[data-test="branch-menu"]').exists()).toBe(false)
  })

  it('com sessão em execução, trocar pede confirmação laranja', async () => {
    useSessionsStore(pinia).setForProject(1, [makeSession({ title: 'Chatbot whatsapp', cwd: PATH, display_state: 'running' })])
    const { wrapper, fetchMock } = mountRepo(makeRepoDetails({ path: PATH, rel_path: 'api', branch: 'develop' }))
    await wrapper.find('[data-test="branch-chip"]').trigger('click')
    await flushPromises()
    await wrapper.find('[data-name="feat/agente"]').trigger('click')
    await flushPromises()
    const dialog = wrapper.find('[role="dialog"]')
    expect(dialog.text()).toContain('Trocar para feat/agente?')
    expect(dialog.text()).toContain('O que ela fizer depois vai cair na branch nova.')
    expect(dialog.find('[data-test="confirm-ok"]').text()).toBe('Trocar mesmo assim')
    await dialog.find('[data-test="confirm-cancel"]').trigger('click')
    expect(posts(fetchMock)).toEqual([])
  })

  it('criar branch: espaço avisa sem chamar o servidor; nome válido cria', async () => {
    const repo = makeRepoDetails({ path: PATH, branch: 'develop', head: '72a11f0', files: [staged('a.ts'), staged('b.ts')] })
    const { wrapper, fetchMock } = mountRepo(repo, { 'POST /api/projects/1/git/branch': () => jsonResponse({ repo }) })
    await wrapper.find('[data-test="branch-chip"]').trigger('click')
    await flushPromises()
    await wrapper.find('[data-test="branch-search"]').setValue('feat novo')
    await wrapper.find('[data-test="branch-create"]').trigger('click')
    const dialog = wrapper.find('[role="dialog"]')
    expect(dialog.text()).toContain('Sai de develop (72a11f0) e troca para ela. As 2 alterações não commitadas vão junto.')
    expect(dialog.find('[data-test="branch-error"]').text()).toBe('Nome de branch não pode ter espaço. Por exemplo: feat-novo.')
    expect(dialog.find('[data-test="confirm-ok"]').attributes('disabled')).toBeDefined()
    await dialog.find('[data-test="branch-name"]').setValue('feat/novo')
    await dialog.find('[data-test="branch-name"]').trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(posts(fetchMock)).toEqual([['branch', { repo: PATH, name: 'feat/novo' }]])
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
  })

  it('erro do servidor ao criar fica no diálogo', async () => {
    const repo = makeRepoDetails({ path: PATH, branch: 'develop' })
    const { wrapper } = mountRepo(repo, {
      'POST /api/projects/1/git/branch': () => jsonResponse({ detail: { code: 'invalid', message: 'Já existe uma branch feat.', output: '' } }, 400),
    })
    await wrapper.find('[data-test="branch-chip"]').trigger('click')
    await flushPromises()
    await wrapper.find('[data-test="branch-search"]').setValue('feat')
    await wrapper.find('[data-test="branch-create"]').trigger('click')
    await wrapper.find('[data-test="confirm-ok"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-test="branch-error"]').text()).toBe('Já existe uma branch feat.')
    expect(wrapper.find('[data-test="scm-error"]').exists()).toBe(false)
  })

  it('o erro do servidor some quando a pessoa muda o nome, e volta se o servidor recusar de novo', async () => {
    const repo = makeRepoDetails({ path: PATH, branch: 'develop' })
    const { wrapper } = mountRepo(repo, {
      'POST /api/projects/1/git/branch': () => jsonResponse({ detail: { code: 'invalid', message: 'Já existe uma branch feat.', output: '' } }, 400),
    })
    await wrapper.find('[data-test="branch-chip"]').trigger('click')
    await flushPromises()
    await wrapper.find('[data-test="branch-search"]').setValue('feat')
    await wrapper.find('[data-test="branch-create"]').trigger('click')
    await wrapper.find('[data-test="confirm-ok"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-test="branch-error"]').exists()).toBe(true)
    await wrapper.find('[data-test="branch-name"]').setValue('feat2')
    expect(wrapper.find('[data-test="branch-error"]').exists()).toBe(false)
    await wrapper.find('[data-test="branch-name"]').setValue('feat')
    await wrapper.find('[data-test="confirm-ok"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-test="branch-error"]').text()).toBe('Já existe uma branch feat.')
  })

  it('mesclar confirma com a contagem e, com conflito, mostra o bloco', async () => {
    const repo = makeRepoDetails({ path: PATH, rel_path: 'api', branch: 'develop' })
    const after = merging(['src/a.vue', 'src/b.ts'], [conflict('src/a.vue'), conflict('src/b.ts'), staged('src/c.ts')])
    const { wrapper, fetchMock } = mountRepo(repo, {
      [`GET /api/projects/1/git/compare?${new URLSearchParams({ repo: PATH, ref: 'refs/heads/feat/agente' })}`]: () => jsonResponse({ incoming: 6 }),
      'POST /api/projects/1/git/merge': () => jsonResponse({ repo: after, conflicts: true }),
    })
    await wrapper.find('[data-test="repo-merge"]').trigger('click')
    await flushPromises()
    await wrapper.find('[data-name="feat/agente"]').trigger('click')
    await flushPromises()
    const dialog = wrapper.find('[role="dialog"]')
    expect(dialog.text()).toContain('Mesclar feat/agente em develop?')
    expect(dialog.text()).toContain('Entram 6 commits de feat/agente.')
    expect(dialog.text()).toContain('develop continua sendo a branch atual.')
    expect(dialog.text()).toContain('Nada é enviado ao remoto.')
    await dialog.find('[data-test="confirm-ok"]').trigger('click')
    await flushPromises()
    expect(posts(fetchMock)).toEqual([['merge', { repo: PATH, ref: 'refs/heads/feat/agente' }]])
    await wrapper.setProps({ repo: after })
    expect(wrapper.find('[data-test="merge-banner"]').text()).toContain('O merge de feat/agente em develop parou em 2 arquivos com conflito.')
    expect(wrapper.find('[data-test="merging-tag"]').exists()).toBe(true)
    expect(wrapper.findAll('[data-test="scm-group-title"]').map((t) => t.text())).toEqual(['Em conflito', 'Prontos para o merge'])
    expect(wrapper.find('[data-test="primary-action"]').text()).toBe('Concluir merge (falta resolver 2)')
    expect((wrapper.find('[data-test="commit-message"]').element as HTMLInputElement).value).toBe("Merge branch 'feat/agente' into develop")
    expect(wrapper.find('[data-test="commit-message"]').attributes('placeholder')).toBe('Mensagem do commit do merge')
  })

  it('marca como resolvido e conclui o merge com a mensagem', async () => {
    const half = merging(['src/a.vue'], [conflict('src/a.vue'), staged('src/c.ts')])
    const done = merging([], [staged('src/a.vue'), staged('src/c.ts')])
    const { wrapper, fetchMock } = mountRepo(half, {
      'POST /api/projects/1/git/resolve': () => jsonResponse({ repo: done }),
      'POST /api/projects/1/git/merge-continue': () => jsonResponse({ repo: makeRepoDetails({ path: PATH }) }),
    })
    const row = wrapper.find('[data-test="scm-group"][data-group="conflict"] [data-test="scm-file"]')
    expect(row.find('[data-test="file-letter"]').text()).toBe('!')
    expect(row.find('[data-test="file-discard"]').exists()).toBe(false)
    await row.find('[data-test="file-resolve"]').trigger('click')
    await flushPromises()
    await wrapper.setProps({ repo: done })
    expect(wrapper.find('[data-test="merge-banner"]').text()).toContain('Conflitos resolvidos')
    const button = wrapper.find('[data-test="primary-action"]')
    expect(button.text()).toBe('Concluir merge')
    await button.trigger('click')
    await flushPromises()
    expect(posts(fetchMock)).toEqual([
      ['resolve', { repo: PATH, paths: ['src/a.vue'] }],
      ['merge-continue', { repo: PATH, message: "Merge branch 'feat/agente' into develop" }],
    ])
  })

  it('arquivo em conflito não oferece Preparar nem Descartar comuns, nem no grupo', () => {
    const { wrapper } = mountRepo(merging(['src/a.vue', 'src/b.ts'], [conflict('src/a.vue'), conflict('src/b.ts'), staged('src/c.ts')]))
    const group = wrapper.find('[data-test="scm-group"][data-group="conflict"]')
    for (const test of ['file-stage', 'file-discard', 'file-unstage', 'group-stage-all', 'group-discard-all', 'group-unstage-all']) {
      expect(group.find(`[data-test="${test}"]`).exists(), test).toBe(false)
    }
    expect(group.findAll('[data-test="file-resolve"]')).toHaveLength(2)
    expect(group.findAll('[data-test="file-editor"]')).toHaveLength(2)
    // Prontos para o merge: nada de tirar da preparação e descartar, que desfariam a resolução.
    const ready = wrapper.find('[data-test="scm-group"][data-group="ready"]')
    expect(ready.find('[data-test="file-discard"]').exists()).toBe(false)
    expect(ready.find('[data-test="file-unstage"]').exists()).toBe(false)
  })

  it('conflito fora de um merge (rebase, por exemplo) também não oferece Preparar nem Descartar', () => {
    const repo = makeRepoDetails({ path: PATH, rel_path: 'api', branch: 'develop', files: [conflict('src/a.vue'), { path: 'novo.ts', status: 'untracked', kind: 'A', added: null, removed: null }] })
    const { wrapper } = mountRepo(repo)
    const group = wrapper.find('[data-test="scm-group"][data-group="conflict"]')
    expect(group.exists()).toBe(true)
    for (const test of ['file-stage', 'file-discard', 'file-resolve', 'group-stage-all', 'group-discard-all']) {
      expect(group.find(`[data-test="${test}"]`).exists(), test).toBe(false)
    }
    expect(wrapper.find('[data-test="scm-group"][data-group="changes"]').findAll('[data-test="scm-file"]')).toHaveLength(1)
    expect(group.find('[data-test="conflict-outside-note"]').text()).toBe('Há conflitos fora de um merge. Resolva pelo terminal.')
    const button = wrapper.find('[data-test="primary-action"]')
    expect(button.attributes('disabled')).toBeDefined()
    expect(button.attributes('title')).toBe('Resolva os conflitos pelo terminal')
    expect(wrapper.find('[data-test="repo-commit"]').attributes('disabled')).toBeDefined()
  })

  it('dentro de um merge o aviso de conflito fora de merge não aparece', () => {
    const { wrapper } = mountRepo(merging(['src/a.vue'], [conflict('src/a.vue')]))
    expect(wrapper.find('[data-test="conflict-outside-note"]').exists()).toBe(false)
  })

  it('diff do arquivo em conflito nomeia as branches', async () => {
    const repo = merging(['src/a.vue'], [conflict('src/a.vue')])
    const { wrapper } = mountRepo(repo, {
      [`GET /api/projects/1/diff?${new URLSearchParams({ repo: 'api', file: 'src/a.vue' })}`]: () => jsonResponse({ diff: '@@ -1 +1,5 @@\n+<<<<<<< HEAD\n+nosso\n+=======\n+deles\n+>>>>>>> feat/agente\n', truncated: false }),
    })
    await wrapper.find('[data-test="scm-file"] [data-test="file-open"]').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('[data-test="conflict-label"]').map((l) => l.text())).toEqual(['(sua branch)', '(a que entra)'])
    expect(wrapper.find('[data-marker="ours"]').text()).toContain('develop')
  })

  it('abortar pede confirmação', async () => {
    const { wrapper, fetchMock } = mountRepo(merging(['a'], [conflict('a')]), { 'POST /api/projects/1/git/merge-abort': () => jsonResponse({ repo: makeRepoDetails({ path: PATH }) }) })
    await wrapper.find('[data-test="merge-abort"]').trigger('click')
    await flushPromises()
    const dialog = wrapper.find('[role="dialog"]')
    expect(dialog.text()).toContain('Abortar o merge?')
    await dialog.find('[data-test="confirm-ok"]').trigger('click')
    await flushPromises()
    expect(posts(fetchMock)).toEqual([['merge-abort', { repo: PATH }]])
  })

  it('Pedir ao Claude cria a sessão, manda o pedido e abre a conversa', async () => {
    const session = makeSession({ session_id: 'nova', project_id: 1 })
    const { wrapper, fetchMock } = mountRepo(merging(['src/a.vue'], [conflict('src/a.vue')]), {
      'POST /api/projects/1/sessions': () => jsonResponse(session),
      'POST /api/sessions/nova/messages': () => jsonResponse({ state: 'running', external_activity: false }),
    })
    await wrapper.find('[data-test="ask-claude"]').trigger('click')
    await flushPromises()
    const [, message] = posts(fetchMock).find(([url]) => String(url).endsWith('messages')) ?? []
    expect(message.text).toContain('o merge de feat/agente em develop parou com conflito')
    expect(router.currentRoute.value.name).toBe('session')
    expect(router.currentRoute.value.params.id).toBe('nova')
  })

  it('driver de merge desliga o botão de merge com o motivo', () => {
    const reason = 'Este repositório tem um driver de merge próprio (npm).'
    const { wrapper } = mountRepo(makeRepoDetails({ path: PATH, state: makeRepoState({ no_merge: reason }) }))
    const button = wrapper.find('[data-test="repo-merge"]')
    expect(button.attributes('disabled')).toBeDefined()
    expect(button.attributes('title')).toBe(reason)
  })

  it('descartar durante o merge avisa que também desfaz o que o merge trouxe', async () => {
    const repo = merging([], [{ path: 'src/d.ts', status: 'unstaged', kind: 'M', added: 2, removed: 1 }, staged('src/c.ts')])
    const { wrapper } = mountRepo(repo)
    const row = wrapper.find('[data-test="scm-group"][data-group="changes"] [data-test="scm-file"]')
    await row.find('[data-test="file-discard"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[role="dialog"]').text()).toContain('Também desfaz o que o merge trouxe para este arquivo.')
  })

  it('fora do merge o descartar não fala do merge', async () => {
    const repo = makeRepoDetails({ path: PATH, files: [{ path: 'src/d.ts', status: 'unstaged', kind: 'M', added: 2, removed: 1 }] })
    const { wrapper } = mountRepo(repo)
    await wrapper.find('[data-test="file-discard"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[role="dialog"]').text()).not.toContain('merge')
  })

  it('a mensagem de merge preenchida pelo app sai quando o merge acaba por fora, mesmo depois de remontar', () => {
    const text = "Merge branch 'feat/agente' into develop"
    localStorage.setItem(`maestro.commitDraft:${PATH}`, text)
    localStorage.setItem(`maestro.mergeMessage:${PATH}`, text)
    const { wrapper } = mountRepo(makeRepoDetails({ path: PATH, branch: 'develop' }))
    expect((wrapper.find('[data-test="commit-message"]').element as HTMLInputElement).value).toBe('')
    expect(localStorage.getItem(`maestro.commitDraft:${PATH}`)).toBeNull()
    expect(localStorage.getItem(`maestro.mergeMessage:${PATH}`)).toBeNull()
  })

  it('o que a pessoa escreveu fica, mesmo com a mensagem de merge guardada', () => {
    localStorage.setItem(`maestro.commitDraft:${PATH}`, 'Corrigir o frete')
    localStorage.setItem(`maestro.mergeMessage:${PATH}`, "Merge branch 'feat/agente' into develop")
    const { wrapper } = mountRepo(makeRepoDetails({ path: PATH, branch: 'develop' }))
    expect((wrapper.find('[data-test="commit-message"]').element as HTMLInputElement).value).toBe('Corrigir o frete')
    expect(localStorage.getItem(`maestro.mergeMessage:${PATH}`)).toBeNull()
  })

  it('ao começar o merge guarda a mensagem preenchida; um rascunho da pessoa não é sobrescrito', () => {
    const { wrapper } = mountRepo(merging(['a'], [conflict('a')]))
    expect((wrapper.find('[data-test="commit-message"]').element as HTMLInputElement).value).toBe("Merge branch 'feat/agente' into develop")
    expect(localStorage.getItem(`maestro.mergeMessage:${PATH}`)).toBe("Merge branch 'feat/agente' into develop")
    wrapper.unmount()
    localStorage.clear()
    localStorage.setItem(`maestro.commitDraft:${PATH}`, 'Meu texto')
    const again = mountRepo(merging(['a'], [conflict('a')]))
    expect((again.wrapper.find('[data-test="commit-message"]').element as HTMLInputElement).value).toBe('Meu texto')
    expect(localStorage.getItem(`maestro.mergeMessage:${PATH}`)).toBeNull()
  })

  it('o merge acabando por fora limpa a mensagem preenchida com o componente de pé', async () => {
    const { wrapper } = mountRepo(merging(['a'], [conflict('a')]))
    await wrapper.setProps({ repo: makeRepoDetails({ path: PATH, branch: 'develop' }) })
    expect((wrapper.find('[data-test="commit-message"]').element as HTMLInputElement).value).toBe('')
  })

  it('segundo clique em mesclar enquanto compara é ignorado e o botão mostra Mesclando…', async () => {
    const repo = makeRepoDetails({ path: PATH, rel_path: 'api', branch: 'develop' })
    let release: (r: Response) => void = () => {}
    let compares = 0
    const { wrapper } = mountRepo(repo, {
      [`GET /api/projects/1/git/compare?${new URLSearchParams({ repo: PATH, ref: 'refs/heads/feat/agente' })}`]: () => {
        compares += 1
        return new Promise<Response>((resolve) => { release = resolve })
      },
    })
    await wrapper.find('[data-test="repo-merge"]').trigger('click')
    await flushPromises()
    await wrapper.find('[data-name="feat/agente"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-test="primary-action"]').text()).toBe('Mesclando…')
    expect(wrapper.find('[data-test="repo-merge"]').attributes('disabled')).toBeDefined()
    expect(wrapper.find('[data-test="branch-chip"]').attributes('disabled')).toBeDefined()
    await wrapper.find('[data-test="repo-merge"]').trigger('click')
    expect(wrapper.find('[data-test="branch-menu"]').exists()).toBe(false)
    release(jsonResponse({ incoming: 2 }))
    await flushPromises()
    expect(compares).toBe(1)
    expect(wrapper.find('[role="dialog"]').text()).toContain('Entram 2 commits de feat/agente.')
    expect(wrapper.find('[data-test="primary-action"]').text()).not.toBe('Mesclando…')
  })

  it('mesclar com sessão em execução pede confirmação laranja com o nome dela', async () => {
    useSessionsStore(pinia).setForProject(1, [makeSession({ title: 'Chatbot whatsapp', cwd: PATH, display_state: 'running' })])
    const { wrapper, fetchMock } = mountRepo(makeRepoDetails({ path: PATH, rel_path: 'api', branch: 'develop' }), {
      [`GET /api/projects/1/git/compare?${new URLSearchParams({ repo: PATH, ref: 'refs/heads/feat/agente' })}`]: () => jsonResponse({ incoming: 1 }),
    })
    await wrapper.find('[data-test="repo-merge"]').trigger('click')
    await flushPromises()
    await wrapper.find('[data-name="feat/agente"]').trigger('click')
    await flushPromises()
    const dialog = wrapper.find('[role="dialog"]')
    expect(dialog.find('[data-test="confirm-running"]').text()).toContain('Chatbot whatsapp')
    expect(dialog.text()).toContain('Mesclar agora muda os arquivos que a sessão está lendo e editando.')
    expect(dialog.text()).toContain('Entra 1 commit de feat/agente.')
    expect(dialog.find('[data-test="confirm-ok"]').text()).toBe('Mesclar mesmo assim')
    expect(dialog.classes().join(' ')).toContain('border-secondary')
    await dialog.find('[data-test="confirm-cancel"]').trigger('click')
    expect(posts(fetchMock)).toEqual([])
  })

  describe('Pedir ao Claude', () => {
    const wide = (matches: boolean) => {
      Object.defineProperty(window, 'matchMedia', {
        configurable: true,
        value: () => ({ matches, addEventListener: () => {}, removeEventListener: () => {} }),
      })
    }
    afterEach(() => { Reflect.deleteProperty(window, 'matchMedia') })
    const session = makeSession({ session_id: 'nova', project_id: 1 })
    const sessionsOk = () => jsonResponse(session)
    const messagesOk = () => jsonResponse({ state: 'running', external_activity: false })
    const count = (fetchMock: ReturnType<typeof routeFetch>, suffix: string) =>
      fetchMock.mock.calls.filter((c) => (c[1] as RequestInit | undefined)?.method === 'POST' && String(c[0]).endsWith(suffix)).length

    it('em tela larga abre a sessão ao lado do projeto', async () => {
      wide(true)
      const { wrapper } = mountRepo(merging(['src/a.vue'], [conflict('src/a.vue')]), {
        'POST /api/projects/1/sessions': sessionsOk, 'POST /api/sessions/nova/messages': messagesOk,
      })
      await wrapper.find('[data-test="ask-claude"]').trigger('click')
      await flushPromises()
      expect(router.currentRoute.value.name).toBe('project')
      expect(router.currentRoute.value.params.id).toBe('1')
      expect(router.currentRoute.value.query.sessao).toBe('nova')
    })

    it('erro ao criar a sessão aparece e o clique seguinte tenta de novo', async () => {
      let fail = true
      const { wrapper, fetchMock } = mountRepo(merging(['src/a.vue'], [conflict('src/a.vue')]), {
        'POST /api/projects/1/sessions': () => (fail ? jsonResponse({ detail: 'Sem espaço para a sessão.' }, 500) : sessionsOk()),
        'POST /api/sessions/nova/messages': messagesOk,
      })
      await wrapper.find('[data-test="ask-claude"]').trigger('click')
      await flushPromises()
      expect(wrapper.text()).toContain('Sem espaço para a sessão.')
      expect(count(fetchMock, 'messages')).toBe(0)
      fail = false
      await wrapper.find('[data-test="ask-claude"]').trigger('click')
      await flushPromises()
      expect(count(fetchMock, '/sessions')).toBe(2)
      expect(count(fetchMock, 'messages')).toBe(1)
      expect(wrapper.text()).not.toContain('Sem espaço para a sessão.')
    })

    it('erro ao enviar guarda a sessão criada e o novo clique reaproveita, sem criar outra', async () => {
      let fail = true
      const { wrapper, fetchMock } = mountRepo(merging(['src/a.vue'], [conflict('src/a.vue')]), {
        'POST /api/projects/1/sessions': sessionsOk,
        'POST /api/sessions/nova/messages': () => (fail ? jsonResponse({ detail: 'Não deu para enviar.' }, 500) : messagesOk()),
      })
      await wrapper.find('[data-test="ask-claude"]').trigger('click')
      await flushPromises()
      expect(wrapper.text()).toContain('Não deu para enviar.')
      fail = false
      await wrapper.find('[data-test="ask-claude"]').trigger('click')
      await flushPromises()
      expect(count(fetchMock, '/sessions')).toBe(1)
      expect(count(fetchMock, 'messages')).toBe(2)
      expect(router.currentRoute.value.params.id).toBe('nova')
    })

    it('o erro some quando o merge termina', async () => {
      const { wrapper } = mountRepo(merging(['src/a.vue'], [conflict('src/a.vue')]), {
        'POST /api/projects/1/sessions': () => jsonResponse({ detail: 'Sem espaço para a sessão.' }, 500),
      })
      await wrapper.find('[data-test="ask-claude"]').trigger('click')
      await flushPromises()
      expect(wrapper.text()).toContain('Sem espaço para a sessão.')
      await wrapper.setProps({ repo: makeRepoDetails({ path: PATH, branch: 'develop' }) })
      expect(wrapper.text()).not.toContain('Sem espaço para a sessão.')
    })
  })
})
