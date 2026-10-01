import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory, type Router } from 'vue-router'
import ProjectView from '../ProjectView.vue'
import { createAppRouter } from '../../router'
import { jsonResponse, makeGitRepo, makeGroup, makeProject, makeRepoCommit, makeRepoDetails, makeSession, routeFetch } from '../../test/factories'
import { useProjectsStore } from '../../stores/projects'
import { useGitStore } from '../../stores/git'
import { useNewConversationStore } from '../../stores/newConversation'
import { useGroupsStore } from '../../stores/groups'

enableAutoUnmount(afterEach)

let pinia: Pinia
let router: Router

beforeEach(async () => {
  pinia = createPinia()
  setActivePinia(pinia)
  router = createAppRouter(createMemoryHistory())
  await router.push('/projects/1')
})

afterEach(() => vi.unstubAllGlobals())

function seed(available = true) {
  const projects = useProjectsStore(pinia)
  projects.projects = [makeProject({ id: 1, name: 'loja-online', available })]
  projects.loaded = true
}

async function mountView() {
  const wrapper = mount(ProjectView, { props: { id: 1 }, global: { plugins: [pinia, router] } })
  await flushPromises()
  return wrapper
}

describe('tela do projeto', () => {
  it('mostra nome, caminho e conversas', async () => {
    seed()
    vi.stubGlobal(
      'fetch',
      routeFetch({
        'GET /api/projects/1/sessions': () =>
          jsonResponse([makeSession({ session_id: 'a', title: 'Cupom expirado', state: 'idle' })]),
      }),
    )
    const wrapper = await mountView()

    expect(wrapper.find('h1').text()).toBe('loja-online')
    expect(wrapper.text()).toContain('/home/vi/dev/loja-online')
    const rows = wrapper.findAll('[data-test="conversation-row"]')
    expect(rows).toHaveLength(1)
    expect(rows[0]!.text()).toContain('Cupom expirado')
    expect(rows[0]!.text()).toContain('Sua vez')
    expect(rows[0]!.find('[data-test="row-link"]').attributes('href')).toBe('/sessions/a')
  })

  it('ordena as conversas por última atividade mesmo com a lista fora de ordem', async () => {
    seed()
    const now = Math.floor(Date.now() / 1000)
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/projects/1/sessions': () => jsonResponse([
        makeSession({ session_id: 'velha', title: 'Velha', last_activity_at: now - 60, created_at: now - 900 }),
        makeSession({ session_id: 'nova', title: 'Nova', last_activity_at: now - 5, created_at: now - 800 }),
        makeSession({ session_id: 'empate-a', title: 'Empate criada antes', last_activity_at: now - 30, created_at: now - 700 }),
        makeSession({ session_id: 'empate-b', title: 'Empate criada depois', last_activity_at: now - 30, created_at: now - 600 }),
      ]),
    }))
    const wrapper = await mountView()

    expect(wrapper.findAll('[data-test="row-link"]').map((r) => r.text())).toEqual([
      'Nova', 'Empate criada depois', 'Empate criada antes', 'Velha',
    ])
  })

  it('lista as conversas do projeto por data com a linha de conversa', async () => {
    seed()
    const now = Date.now() / 1000
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/projects/1/sessions': () => jsonResponse([
      makeSession({ session_id: 'a', title: 'Hoje', last_activity_at: now }),
      makeSession({ session_id: 'b', title: 'Velha', last_activity_at: now - 30 * 86400, display_state: 'finished' }),
    ]) }))
    const wrapper = await mountView()

    expect(wrapper.findAll('[data-test="row-link"]').map((r) => r.text())).toEqual(['Hoje', 'Velha'])
    expect(wrapper.findAll('[data-test="date-group"]').map((g) => g.text())).toEqual(['Hoje', 'Antes'])
  })

  it('sem conversas mostra a orientação para começar uma', async () => {
    seed()
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/projects/1/sessions': () => jsonResponse([]) }))
    const wrapper = await mountView()

    expect(wrapper.text()).toContain('Nenhuma conversa ainda. Use "Nova sessão" para começar uma conversa nesta pasta.')
    expect(wrapper.find('[data-test="conversation-row"]').exists()).toBe(false)
  })

  it('"Nova sessão" abre o modal de nova conversa neste projeto', async () => {
    seed()
    const fetchMock = routeFetch({ 'GET /api/projects/1/sessions': () => jsonResponse([]) })
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = await mountView()

    await wrapper.find('[data-test="new-session"]').trigger('click')
    await flushPromises()

    const store = useNewConversationStore(pinia)
    expect(store.isOpen).toBe(true)
    expect(store.presetProjectId).toBe(1)
    expect(fetchMock).not.toHaveBeenCalledWith('/api/projects/1/sessions', expect.objectContaining({ method: 'POST' }))
  })

  it('desabilita "Nova sessão" com explicação quando a pasta está indisponível', async () => {
    seed(false)
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/projects/1/sessions': () => jsonResponse([]) }))
    const wrapper = await mountView()

    const button = wrapper.find('[data-test="new-session"]')
    expect(button.attributes('disabled')).toBeDefined()
    const hintId = button.attributes('aria-describedby')!
    expect(wrapper.find(`#${hintId}`).text()).toContain('não existe mais')
  })

  it('remover pede confirmação e explica que a pasta e as conversas ficam', async () => {
    seed()
    const fetchMock = routeFetch({
      'GET /api/projects/1/sessions': () => jsonResponse([]),
      'DELETE /api/projects/1': () => new Response(null, { status: 204 }),
    })
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = await mountView()

    await wrapper.find('[data-test="remove"]').trigger('click')
    const dialog = wrapper.find('[data-test="confirm-remove"]')
    expect(dialog.exists()).toBe(true)
    expect(dialog.text()).toContain('A pasta e as conversas não são apagadas')
    expect(fetchMock).not.toHaveBeenCalledWith('/api/projects/1', expect.objectContaining({ method: 'DELETE' }))

    await dialog.find('[data-test="confirm-remove-cancel"]').trigger('click')
    expect(wrapper.find('[data-test="confirm-remove"]').exists()).toBe(false)

    await wrapper.find('[data-test="remove"]').trigger('click')
    await wrapper.find('[data-test="confirm-remove-ok"]').trigger('click')
    await flushPromises()

    expect(fetchMock).toHaveBeenCalledWith('/api/projects/1', expect.objectContaining({ method: 'DELETE' }))
    expect(useProjectsStore(pinia).projects).toEqual([])
    expect(router.currentRoute.value.fullPath).toBe('/inbox')
  })

  it('renomeia o projeto', async () => {
    seed()
    vi.stubGlobal(
      'fetch',
      routeFetch({
        'GET /api/projects/1/sessions': () => jsonResponse([]),
        'PATCH /api/projects/1': (init) =>
          jsonResponse(makeProject({ id: 1, name: JSON.parse(init!.body as string).name })),
      }),
    )
    const wrapper = await mountView()

    await wrapper.find('[data-test="rename"]').trigger('click')
    await wrapper.find('#rename-project').setValue('loja-nova')
    await wrapper.find('[data-test="rename-form"]').trigger('submit')
    await flushPromises()

    expect(wrapper.find('h1').text()).toBe('loja-nova')
    expect(useProjectsStore(pinia).byId(1)?.name).toBe('loja-nova')
  })

  it('Esc no renomear fecha o formulário e consome o Esc', async () => {
    seed()
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/projects/1/sessions': () => jsonResponse([]) }))
    const wrapper = await mountView()
    await wrapper.find('[data-test="rename"]').trigger('click')
    const event = new KeyboardEvent('keydown', { key: 'Escape', cancelable: true, bubbles: true })
    wrapper.find('#rename-project').element.dispatchEvent(event)
    await flushPromises()
    expect(event.defaultPrevented).toBe(true)
    expect(wrapper.find('[data-test="rename-form"]').exists()).toBe(false)
  })

  it('avisa quando o projeto não existe', async () => {
    const projects = useProjectsStore(pinia)
    projects.loaded = true
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/projects/1/sessions': () => jsonResponse({ detail: 'Projeto não encontrado.' }, 404) }))
    const wrapper = await mountView()
    expect(wrapper.text()).toContain('Projeto não encontrado')
  })

  it('Atualizar sincroniza o projeto com o histórico', async () => {
    seed()
    const sync = vi.fn(() => jsonResponse([makeSession({ session_id: 'nova', title: 'Veio do CLI' })]))
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/projects/1/sessions': () => jsonResponse([]),
      'POST /api/projects/1/sync': sync,
    }))
    const wrapper = await mountView()
    await wrapper.find('[data-test="sync"]').trigger('click')
    await flushPromises()
    expect(sync).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('Veio do CLI')
  })

  it('Atualizar recarrega também a lista de projetos', async () => {
    seed()
    const list = vi.fn(() => jsonResponse([makeProject({ id: 1, name: 'loja-online', hidden_sessions: 2 })]))
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/projects/1/sessions': () => jsonResponse([]),
      'POST /api/projects/1/sync': () => jsonResponse([]),
      'GET /api/projects': list,
    }))
    const wrapper = await mountView()
    await wrapper.find('[data-test="sync"]').trigger('click')
    await flushPromises()
    expect(list).toHaveBeenCalledTimes(1)
    expect(useProjectsStore(pinia).byId(1)?.hidden_sessions).toBe(2)
  })

  it('confirmação de remoção: foco vai para Cancelar, Esc fecha e devolve o foco a Remover', async () => {
    seed()
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/projects/1/sessions': () => jsonResponse([]) }))
    const wrapper = mount(ProjectView, { props: { id: 1 }, attachTo: document.body, global: { plugins: [pinia, router] } })
    await flushPromises()
    await wrapper.find('[data-test="remove"]').trigger('click')
    await flushPromises()
    expect(document.activeElement).toBe(wrapper.find('[data-test="confirm-remove-cancel"]').element)
    await wrapper.find('[data-test="confirm-remove"]').trigger('keydown', { key: 'Escape' })
    await flushPromises()
    expect(wrapper.find('[data-test="confirm-remove"]').exists()).toBe(false)
    expect(document.activeElement).toBe(wrapper.find('[data-test="remove"]').element)
    wrapper.unmount()
  })

  it('avisa quando o projeto tem mais de 50 repositórios', async () => {
    seed()
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/projects/1/sessions': () => jsonResponse([]),
      'GET /api/projects/1/git': () => jsonResponse({ repos: [makeGitRepo()], limit_reached: true }),
      'GET /api/projects/1/git/details': () => jsonResponse({ repos: [makeRepoDetails()], limit_reached: true }),
    }))
    const wrapper = await mountView()
    expect(wrapper.find('[data-test="repo-limit"]').text()).toContain('Mais de 50 repositórios; só os 50 primeiros são acompanhados.')
  })

  it('sem o limite não mostra o aviso e mostra HEAD solto', async () => {
    seed()
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/projects/1/sessions': () => jsonResponse([]),
      'GET /api/projects/1/git': () => jsonResponse({ repos: [makeGitRepo({ branch: null, detached: true, head: 'abc1234' })], limit_reached: false }),
      'GET /api/projects/1/git/details': () => jsonResponse({
        repos: [makeRepoDetails({ branch: null, detached: true, head: 'abc1234' })], limit_reached: false,
      }),
    }))
    const wrapper = await mountView()
    expect(wrapper.find('[data-test="repo-limit"]').exists()).toBe(false)
    expect(useGitStore(pinia).limitReached(1)).toBe(false)
    expect(wrapper.find('[data-test="repo"]').text()).toContain('HEAD solto · abc1234')
  })

  it('a lista por data mostra só as conversas sem agrupador e ganha o título "Sem agrupador"', async () => {
    seed()
    useGroupsStore(pinia).groups = [makeGroup({ id: 1, project_id: 1, name: 'Checkout' })]
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/projects/1/sessions': () => jsonResponse([
      makeSession({ session_id: 'a', title: 'Agrupada', group_id: 1 }),
      makeSession({ session_id: 'b', title: 'Solta', group_id: null }),
    ]) }))
    const wrapper = await mountView()

    const dated = wrapper.findAll('[data-test="date-group"]').map((g) => g.element.closest('section')!)
    expect(dated).toHaveLength(1)
    expect(dated[0]!.textContent).toContain('Solta')
    expect(dated[0]!.textContent).not.toContain('Agrupada')
    expect(wrapper.find('[data-test="ungrouped-title"]').text()).toBe('Sem agrupador')
    expect(wrapper.find('[data-test="group-section"]').text()).toContain('Agrupada')
  })

  it('conversa com agrupador desconhecido ou de outro projeto conta como sem agrupador', async () => {
    seed()
    useGroupsStore(pinia).groups = [
      makeGroup({ id: 1, project_id: 1, name: 'Checkout' }),
      makeGroup({ id: 7, project_id: 2, name: 'De outro' }),
    ]
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/projects/1/sessions': () => jsonResponse([
      makeSession({ session_id: 'a', title: 'Agrupada', group_id: 1 }),
      makeSession({ session_id: 'b', title: 'Alheia', group_id: 7 }),
      makeSession({ session_id: 'c', title: 'Fantasma', group_id: 99 }),
    ]) }))
    const wrapper = await mountView()

    const dated = wrapper.findAll('[data-test="date-group"]').map((g) => g.element.closest('section')!)
    expect(dated).toHaveLength(1)
    expect(dated[0]!.textContent).toContain('Alheia')
    expect(dated[0]!.textContent).toContain('Fantasma')
    expect(dated[0]!.textContent).not.toContain('Agrupada')
  })

  it('sem os agrupadores carregados as conversas agrupadas continuam na lista', async () => {
    seed()
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/projects/1/sessions': () => jsonResponse([
      makeSession({ session_id: 'a', title: 'Agrupada', group_id: 1 }),
    ]) }))
    const wrapper = await mountView()
    expect(wrapper.findAll('[data-test="date-group"]')).toHaveLength(1)
    expect(wrapper.text()).toContain('Agrupada')
  })

  it('sem agrupadores não mostra o título "Sem agrupador"', async () => {
    seed()
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/projects/1/sessions': () => jsonResponse([makeSession({ session_id: 'b', title: 'Solta' })]) }))
    const wrapper = await mountView()
    expect(wrapper.find('[data-test="ungrouped-title"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="groups-empty"]').exists()).toBe(true)
  })

  it('mostra o estado git de cada repositório: sincronização, arquivos e commits', async () => {
    seed()
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/projects/1/sessions': () => jsonResponse([]),
      'GET /api/projects/1/git': () => jsonResponse({ repos: [makeGitRepo()], limit_reached: false }),
      'GET /api/projects/1/git/details': () => jsonResponse({
        repos: [makeRepoDetails({
          ahead: 1,
          files: [{ path: 'src/a.py', status: 'unstaged', added: 2, removed: 1 }],
          commits: [makeRepoCommit({ subject: 'Ajustar o carrinho', pushed: false })],
        })],
        limit_reached: false,
      }),
    }))
    const wrapper = await mountView()
    const repo = wrapper.find('[data-test="repos"] [data-test="repo"]')
    expect(repo.text()).toContain('loja-online')
    expect(repo.text()).toContain('1 para subir')
    expect(repo.text()).toContain('1 não commitados')
    expect(repo.text()).toContain('src/a.py')
    expect(repo.text()).toContain('Ajustar o carrinho')
  })

  it('sem repositório git não monta a visão de detalhes', async () => {
    seed()
    const fetchMock = routeFetch({
      'GET /api/projects/1/sessions': () => jsonResponse([]),
      'GET /api/projects/1/git': () => jsonResponse({ repos: [], limit_reached: false }),
    })
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = await mountView()
    expect(wrapper.find('[data-test="repos"]').text()).toContain('sem repositório git')
    expect(fetchMock.mock.calls.some((c) => String(c[0]).endsWith('/git/details'))).toBe(false)
  })
})
