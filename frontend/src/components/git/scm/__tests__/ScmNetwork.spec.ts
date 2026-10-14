import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import ScmRepo from '../ScmRepo.vue'
import ScmSection from '../ScmSection.vue'
import { useGitDetailsStore } from '../../../../stores/gitDetails'
import { useProjectsStore } from '../../../../stores/projects'
import { useSessionsStore } from '../../../../stores/sessions'
import { jsonResponse, makeProject, makeRepoDetails, makeRepoState, makeSession, routeFetch } from '../../../../test/factories'
import type { RepoDetails } from '../../../../types/api'

enableAutoUnmount(afterEach)
const PATH = '/home/vi/dev/loja/api'
let pinia: Pinia
const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: { template: '<div />' } }] })

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
  const wrapper = mount(ScmRepo, { props: { projectId: 1, repo, collapseAll: 0, startOpen: true }, global: { plugins: [pinia, router] }, attachTo: document.body })
  return { wrapper, fetchMock }
}
const kinds = (fetchMock: ReturnType<typeof routeFetch>) =>
  fetchMock.mock.calls.filter((c) => (c[1] as RequestInit | undefined)?.method === 'POST').map((c) => String(c[0]).split('/git/').pop())

describe('rede no repositório', () => {
  it('o botão largo sincroniza, envia, baixa e publica', async () => {
    const answer = () => jsonResponse({ repo: makeRepoDetails({ path: PATH }), conflicts: false, remote: 'origin' })
    for (const [repo, label, kind] of [
      [makeRepoDetails({ path: PATH, ahead: 14, behind: 2 }), 'Sincronizar 2↓ 14↑', 'sync'],
      [makeRepoDetails({ path: PATH, ahead: 3, behind: 0 }), 'Enviar 3 commits', 'push'],
      [makeRepoDetails({ path: PATH, ahead: 0, behind: 1 }), 'Baixar 1 commit', 'pull'],
      [makeRepoDetails({ path: PATH, upstream: null, ahead: null, behind: null }), 'Publicar branch em origin', 'publish'],
    ] as const) {
      const { wrapper, fetchMock } = mountRepo(repo, { [`POST /api/projects/1/git/${kind}`]: answer })
      const button = wrapper.find('[data-test="primary-action"]')
      expect(button.text()).toBe(label)
      await button.trigger('click')
      await flushPromises()
      expect(kinds(fetchMock)).toEqual([kind])
      wrapper.unmount()
    }
  })

  it('ícones de baixar e enviar na linha, desligados quando não há o que fazer', async () => {
    const { wrapper, fetchMock } = mountRepo(makeRepoDetails({ path: PATH, ahead: 2, behind: 0 }), {
      'POST /api/projects/1/git/push': () => jsonResponse({ repo: makeRepoDetails({ path: PATH }) }),
    })
    expect(wrapper.find('[data-test="repo-pull"]').attributes('disabled')).toBeDefined()
    expect(wrapper.find('[data-test="repo-push"]').attributes('title')).toBe('Enviar (push)')
    await wrapper.find('[data-test="repo-push"]').trigger('click')
    await flushPromises()
    expect(kinds(fetchMock)).toEqual(['push'])
    wrapper.unmount()
    const { wrapper: clean } = mountRepo(makeRepoDetails({ path: PATH }))
    expect(clean.find('[data-test="repo-push"]').attributes('title')).toBe('Nada para enviar')
  })

  it('baixar com sessão em execução pede confirmação; enviar não', async () => {
    useSessionsStore(pinia).setForProject(1, [makeSession({ title: 'Chatbot', cwd: PATH, display_state: 'running' })])
    const { wrapper, fetchMock } = mountRepo(makeRepoDetails({ path: PATH, rel_path: 'api', ahead: 1, behind: 2 }), {
      'POST /api/projects/1/git/sync': () => jsonResponse({ repo: makeRepoDetails({ path: PATH }), conflicts: false }),
      'POST /api/projects/1/git/push': () => jsonResponse({ repo: makeRepoDetails({ path: PATH }) }),
    })
    await wrapper.find('[data-test="primary-action"]').trigger('click')
    const dialog = wrapper.find('[role="dialog"]')
    expect(dialog.text()).toContain('Baixar agora muda os arquivos que a sessão está lendo e editando.')
    expect(dialog.find('[data-test="confirm-ok"]').text()).toBe('Sincronizar mesmo assim')
    await dialog.find('[data-test="confirm-cancel"]').trigger('click')
    await wrapper.find('[data-test="repo-push"]').trigger('click')
    await flushPromises()
    expect(kinds(fetchMock)).toEqual(['push'])
  })

  it('baixar que para em conflito abre o bloco do merge', async () => {
    const conflicted = makeRepoDetails({
      path: PATH, files: [{ path: 'README.md', status: 'conflict', kind: 'U', added: null, removed: null }],
      state: makeRepoState({ merging: true, merge_branch: 'origin/main', conflicts: ['README.md'] }),
    })
    const { wrapper } = mountRepo(makeRepoDetails({ path: PATH, ahead: 0, behind: 1 }), {
      'POST /api/projects/1/git/pull': () => jsonResponse({ repo: conflicted, conflicts: true }),
    })
    await wrapper.find('[data-test="primary-action"]').trigger('click')
    await flushPromises()
    await wrapper.setProps({ repo: conflicted })
    expect(wrapper.find('[data-test="merge-banner"]').exists()).toBe(true)
  })

  it('envio recusado mostra a mensagem e a saída', async () => {
    const { wrapper } = mountRepo(makeRepoDetails({ path: PATH, ahead: 1, behind: 0 }), {
      'POST /api/projects/1/git/push': () => jsonResponse({ detail: { code: 'git', message: 'O envio não foi feito: origin/main recebeu commits que você ainda não tem. Sincronize para baixar e enviar.', output: ' ! [rejected] main -> main (fetch first)' } }, 409),
    })
    await wrapper.find('[data-test="primary-action"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-test="scm-error"]').text()).toContain('Sincronize para baixar e enviar.')
    await wrapper.find('[data-test="show-output"]').trigger('click')
    expect(wrapper.find('[data-test="scm-error-output"]').text()).toContain('[rejected]')
  })

  it('o menu Mais ações busca no remoto, copia o caminho e aborta o merge', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    const repo = makeRepoDetails({ path: PATH, state: makeRepoState({ merging: true, merge_branch: 'feat', conflicts: [] }) })
    const { wrapper, fetchMock } = mountRepo(repo, {
      'POST /api/projects/1/git/fetch-repo': () => jsonResponse({ repo }),
      'POST /api/projects/1/git/merge-abort': () => jsonResponse({ repo: makeRepoDetails({ path: PATH }) }),
    })
    await wrapper.find('[data-test="repo-more"]').trigger('click')
    await wrapper.find('[data-test="menu-fetch"]').trigger('click')
    await flushPromises()
    await wrapper.find('[data-test="repo-more"]').trigger('click')
    await wrapper.find('[data-test="menu-copy-path"]').trigger('click')
    expect(writeText).toHaveBeenCalledWith(PATH)
    await wrapper.find('[data-test="repo-more"]').trigger('click')
    await wrapper.find('[data-test="menu-abort"]').trigger('click')
    await wrapper.find('[data-test="confirm-ok"]').trigger('click')
    await flushPromises()
    expect(kinds(fetchMock)).toEqual(['fetch-repo', 'merge-abort'])
  })

  it('o ocupado de rede aparece no botão largo', async () => {
    let release!: () => void
    const { wrapper } = mountRepo(makeRepoDetails({ path: PATH, ahead: 0, behind: 3 }), {
      'POST /api/projects/1/git/pull': () => new Promise<Response>((r) => { release = () => r(jsonResponse({ repo: makeRepoDetails({ path: PATH }), conflicts: false })) }),
    })
    await wrapper.find('[data-test="primary-action"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-test="primary-action"]').text()).toBe('Baixando 3 commits…')
    release()
    await flushPromises()
  })

  it('o menu fecha com Esc, clique fora e foco saindo, e devolve o foco ao botão', async () => {
    const { wrapper } = mountRepo(makeRepoDetails({ path: PATH }))
    const more = wrapper.find('[data-test="repo-more"]')
    await more.trigger('click')
    expect(wrapper.find('[data-test="repo-menu"]').exists()).toBe(true)
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    await flushPromises()
    expect(wrapper.find('[data-test="repo-menu"]').exists()).toBe(false)
    expect(document.activeElement).toBe(more.element)

    await more.trigger('click')
    await wrapper.find('[data-test="repo-menu-backdrop"]').trigger('click')
    expect(wrapper.find('[data-test="repo-menu"]').exists()).toBe(false)

    await more.trigger('click')
    await flushPromises()
    const outside = document.createElement('button')
    document.body.append(outside)
    await wrapper.find('[data-test="repo-menu"]').trigger('focusout', { relatedTarget: outside })
    expect(wrapper.find('[data-test="repo-menu"]').exists()).toBe(false)
    outside.remove()
  })

  it('o ícone Baixar com commits para enviar e para baixar só baixa, e pergunta "Baixar agora?" com sessão rodando', async () => {
    useSessionsStore(pinia).setForProject(1, [makeSession({ title: 'Chatbot', cwd: PATH, display_state: 'running' })])
    const { wrapper, fetchMock } = mountRepo(makeRepoDetails({ path: PATH, ahead: 1, behind: 2 }), {
      'POST /api/projects/1/git/pull': () => jsonResponse({ repo: makeRepoDetails({ path: PATH }), conflicts: false }),
    })
    await wrapper.find('[data-test="repo-pull"]').trigger('click')
    const dialog = wrapper.find('[role="dialog"]')
    expect(dialog.text()).toContain('Baixar agora?')
    await dialog.find('[data-test="confirm-ok"]').trigger('click')
    await flushPromises()
    expect(kinds(fetchMock)).toEqual(['pull'])
  })

  it('Buscar no remoto continua disponível num repositório só leitura', async () => {
    const repo = makeRepoDetails({ path: PATH, state: makeRepoState({ read_only: 'Este repositório usa LFS.' }) })
    const { wrapper, fetchMock } = mountRepo(repo, { 'POST /api/projects/1/git/fetch-repo': () => jsonResponse({ repo }) })
    await wrapper.find('[data-test="repo-more"]').trigger('click')
    expect(wrapper.find('[data-test="menu-fetch"]').attributes('disabled')).toBeUndefined()
    await wrapper.find('[data-test="menu-fetch"]').trigger('click')
    await flushPromises()
    expect(kinds(fetchMock)).toEqual(['fetch-repo'])
  })

  it.each([
    ['em merge', { state: makeRepoState({ merging: true, merge_branch: 'feat', conflicts: [] }), ahead: 1, behind: 1 },
      'Conclua ou aborte o merge antes de baixar', 'Conclua ou aborte o merge antes de enviar'],
    ['sem upstream', { upstream: null, ahead: null, behind: null },
      'Esta branch não acompanha nenhuma branch remota. Use Publicar.', 'Esta branch não acompanha nenhuma branch remota. Use Publicar.'],
    ['com HEAD solto', { detached: true, branch: null, upstream: null, ahead: null, behind: null },
      'O HEAD está solto: não há branch para baixar.', 'O HEAD está solto: não há branch para enviar.'],
    ['só leitura', { state: makeRepoState({ read_only: 'Este repositório usa LFS.' }), ahead: 1, behind: 1 },
      'Este repositório usa LFS.', 'Este repositório usa LFS.'],
    ['sem o que baixar', { ahead: 1, behind: 0 }, 'Nada para baixar', 'Enviar (push)'],
    ['sem o que enviar', { ahead: 0, behind: 1 }, 'Baixar (pull)', 'Nada para enviar'],
  ] as const)('os títulos dos ícones dizem por que estão desligados: %s', (_label, overrides, pull, push) => {
    const { wrapper } = mountRepo(makeRepoDetails({ path: PATH, ...overrides } as Partial<RepoDetails>))
    expect(wrapper.find('[data-test="repo-pull"]').attributes('title')).toBe(pull)
    expect(wrapper.find('[data-test="repo-push"]').attributes('title')).toBe(push)
  })

  it('em repositório só leitura, Mesclar, Commitar, Baixar e Enviar ficam desligados com o motivo', () => {
    const reason = 'Este repositório usa LFS.'
    const { wrapper } = mountRepo(makeRepoDetails({ path: PATH, ahead: 1, behind: 1, state: makeRepoState({ read_only: reason }) }))
    for (const test of ['repo-merge', 'repo-commit', 'repo-pull', 'repo-push']) {
      const button = wrapper.find(`[data-test="${test}"]`)
      expect(button.exists(), test).toBe(true)
      expect(button.attributes('disabled'), test).toBeDefined()
      expect(button.attributes('title'), test).toBe(reason)
    }
  })

  it('o motivo do no_merge vira o título do Baixar, e Ctrl+Enter não baixa com a ação desligada', async () => {
    const { wrapper, fetchMock } = mountRepo(makeRepoDetails({ path: PATH, ahead: 0, behind: 2, state: makeRepoState({ no_merge: 'Este repositório usa um merge driver. Baixe pelo terminal.' }) }))
    expect(wrapper.find('[data-test="repo-pull"]').attributes('title')).toBe('Este repositório usa um merge driver. Baixe pelo terminal.')
    expect(wrapper.find('[data-test="primary-action"]').attributes('disabled')).toBeDefined()
    await wrapper.find('[data-test="commit-message"]').trigger('keydown', { key: 'Enter', ctrlKey: true })
    await flushPromises()
    expect(kinds(fetchMock)).toEqual([])
  })

  it.each([
    ['Enviar', { ahead: 1, behind: 0 }],
    ['Baixar', { ahead: 0, behind: 2 }],
    ['Sincronizar', { ahead: 1, behind: 2 }],
    ['Publicar', { upstream: null, ahead: null, behind: null, state: makeRepoState({ remotes: ['origin'] }) }],
  ] as const)('Ctrl+Enter com %s ligado não faz nada: só o clique dispara a rede', async (_label, overrides) => {
    const { wrapper, fetchMock } = mountRepo(makeRepoDetails({ path: PATH, ...overrides } as Partial<RepoDetails>))
    expect(wrapper.find('[data-test="primary-action"]').attributes('disabled')).toBeUndefined()
    await wrapper.find('[data-test="commit-message"]').trigger('keydown', { key: 'Enter', ctrlKey: true })
    await flushPromises()
    expect(kinds(fetchMock)).toEqual([])
  })

  it.each([
    ['sem alterações e com commits para enviar', { ahead: 1, behind: 0 }, 'Nada para commitar'],
    ['sem alterações e sem nada a fazer', { ahead: 0, behind: 0 }, 'Não há alterações para commitar'],
    ['com alterações e sem mensagem', { files: [{ path: 'a.ts', status: 'unstaged', kind: 'M', added: 1, removed: 0 }] }, 'Escreva a mensagem do commit'],
    ['em merge', { state: makeRepoState({ merging: true, merge_branch: 'feat', conflicts: [] }) }, 'Conclua o merge com Concluir merge'],
  ] as const)('o título do ícone Commitar diz por que está desligado: %s', (_label, overrides, title) => {
    const { wrapper } = mountRepo(makeRepoDetails({ path: PATH, ...overrides } as Partial<RepoDetails>))
    expect(wrapper.find('[data-test="repo-commit"]').attributes('disabled')).toBeDefined()
    expect(wrapper.find('[data-test="repo-commit"]').attributes('title')).toBe(title)
  })

  it('sem commits o ícone Mesclar diz "Ainda não há commits."', () => {
    const { wrapper } = mountRepo(makeRepoDetails({ path: PATH, head: null, branch: 'main', upstream: null, ahead: null, behind: null }))
    expect(wrapper.find('[data-test="repo-merge"]').attributes('disabled')).toBeDefined()
    expect(wrapper.find('[data-test="repo-merge"]').attributes('title')).toBe('Ainda não há commits.')
  })

  it('o chip de branch em repositório só leitura diz o motivo', () => {
    const reason = 'Este repositório usa LFS.'
    const { wrapper } = mountRepo(makeRepoDetails({ path: PATH, state: makeRepoState({ read_only: reason }) }))
    expect(wrapper.find('[data-test="branch-chip"]').attributes('disabled')).toBeDefined()
    expect(wrapper.find('[data-test="branch-chip"]').attributes('title')).toBe(reason)
  })

  it('com uma ação em andamento, Commitar, Mesclar e o chip de branch dizem o rótulo de ocupado', async () => {
    let release!: () => void
    const { wrapper } = mountRepo(makeRepoDetails({ path: PATH, ahead: 0, behind: 3 }), {
      'POST /api/projects/1/git/pull': () => new Promise<Response>((r) => { release = () => r(jsonResponse({ repo: makeRepoDetails({ path: PATH }), conflicts: false })) }),
    })
    await wrapper.find('[data-test="primary-action"]').trigger('click')
    await flushPromises()
    for (const test of ['repo-commit', 'repo-merge', 'branch-chip']) {
      expect(wrapper.find(`[data-test="${test}"]`).attributes('disabled'), test).toBeDefined()
      expect(wrapper.find(`[data-test="${test}"]`).attributes('title'), test).toBe('Baixando 3 commits…')
    }
    release()
    await flushPromises()
  })

  it('o erro da operação aparece com o repositório recolhido e pode ser fechado', async () => {
    const repo = makeRepoDetails({ path: PATH })
    useGitDetailsStore(pinia).byProject[1] = { repos: [repo], limit_reached: false }
    vi.stubGlobal('fetch', routeFetch({
      'POST /api/projects/1/git/fetch-repo': () => jsonResponse({ detail: { code: 'git', message: 'Não foi possível buscar: a chave ssh foi recusada.', output: 'Permission denied (publickey).' } }, 409),
    }))
    const wrapper = mount(ScmRepo, { props: { projectId: 1, repo, collapseAll: 0, startOpen: false }, global: { plugins: [pinia, router] }, attachTo: document.body })
    expect(wrapper.find('[data-test="scm-body"]').exists()).toBe(false)
    await wrapper.find('[data-test="repo-more"]').trigger('click')
    await wrapper.find('[data-test="menu-fetch"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-test="scm-body"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="scm-error"]').text()).toContain('a chave ssh foi recusada.')
    await wrapper.find('[data-test="show-output"]').trigger('click')
    expect(wrapper.find('[data-test="scm-error-output"]').text()).toContain('Permission denied')
    await wrapper.find('[data-test="dismiss-error"]').trigger('click')
    expect(wrapper.find('[data-test="scm-error"]').exists()).toBe(false)
  })
})

describe('Buscar em todos', () => {
  it('busca nos repositórios com upstream', async () => {
    const repos = [
      makeRepoDetails({ path: '/p/a', rel_path: 'a' }),
      makeRepoDetails({ path: '/p/b', rel_path: 'b', upstream: null, ahead: null, behind: null }),
      makeRepoDetails({ path: '/p/c', rel_path: 'c', error: 'quebrado' }),
    ]
    const fetchMock = routeFetch({
      'GET /api/projects/1/git/details': () => jsonResponse({ repos, limit_reached: false }),
      'POST /api/projects/1/git/fetch-repo': () => jsonResponse({ repo: repos[0] }),
    })
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = mount(ScmSection, { props: { projectId: 1 }, global: { plugins: [pinia, router] } })
    await flushPromises()
    await wrapper.find('[data-test="scm-fetch-all"]').trigger('click')
    await flushPromises()
    const bodies = fetchMock.mock.calls.filter((c) => String(c[0]).endsWith('fetch-repo')).map((c) => JSON.parse(String((c[1] as RequestInit).body)).repo)
    expect(bodies).toEqual(['/p/a'])
  })

  it('a falha de um repositório recolhido aparece na linha dele', async () => {
    const repos = [
      makeRepoDetails({ path: '/p/a', rel_path: 'a' }),
      makeRepoDetails({ path: '/p/b', rel_path: 'b' }),
    ]
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/projects/1/git/details': () => jsonResponse({ repos, limit_reached: false }),
      'POST /api/projects/1/git/fetch-repo': () => jsonResponse({ detail: { code: 'git', message: 'Não foi possível buscar: a chave ssh foi recusada.', output: '' } }, 409),
    }))
    const wrapper = mount(ScmSection, { props: { projectId: 1 }, global: { plugins: [pinia, router] } })
    await flushPromises()
    expect(wrapper.find('[data-test="scm-body"]').exists()).toBe(false)
    await wrapper.find('[data-test="scm-fetch-all"]').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('[data-test="scm-error"]')).toHaveLength(2)
    expect(wrapper.find('[data-test="scm-error"]').text()).toContain('a chave ssh foi recusada.')
  })
})
