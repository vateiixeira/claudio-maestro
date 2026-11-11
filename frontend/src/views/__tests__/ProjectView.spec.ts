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
  it('resposta atrasada do projeto anterior não apaga carregamento nem injeta erro no atual', async () => {
    seed()
    useProjectsStore().projects.push(makeProject({ id: 2, name: 'Outro' }))
    let first!: (r: Response) => void
    let second!: (r: Response) => void
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/projects/1/sessions': () => new Promise<Response>(resolve => { first = resolve }),
      'GET /api/projects/2/sessions': () => new Promise<Response>(resolve => { second = resolve }),
    }))
    const wrapper = await mountView()
    await wrapper.setProps({ id: 2 })
    await flushPromises()
    first(jsonResponse({ detail: 'Falha do projeto anterior' }, 500))
    await flushPromises()
    expect(wrapper.get('[data-test="conversations-loading"]').text()).toContain('Carregando')
    expect(wrapper.text()).not.toContain('Falha do projeto anterior')
    second(jsonResponse([makeSession({ session_id: 'outro', project_id: 2, title: 'Conversa atual' })]))
    await flushPromises()
    expect(wrapper.find('[data-test="conversations-loading"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('Conversa atual')
  })

  it('começa em Conversas e só busca detalhes Git ao abrir sua aba', async () => {
    seed()
    const fetchMock = routeFetch({
      'GET /api/projects/1/sessions': () => jsonResponse([]),
      'GET /api/projects/1/git': () => jsonResponse({ repos: [makeGitRepo()], limit_reached: false }),
      'GET /api/projects/1/git/details': () => jsonResponse({ repos: [makeRepoDetails()], limit_reached: false }),
    })
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = await mountView()
    expect(wrapper.get('[data-test="project-tab-conversas"]').attributes('aria-selected')).toBe('true')
    expect(wrapper.find('[data-test="scm-section"]').exists()).toBe(false)
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes('/git/details') || String(url).includes('/git/log'))).toBe(false)
    await wrapper.get('[data-test="project-tab-git"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.query.visao).toBe('git')
    expect(wrapper.find('[data-test="scm-section"]').exists()).toBe(true)
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/git/details'))).toHaveLength(1)
  })

  it('as abas respondem a teclado, URL e voltar sem apagar a conversa ao lado', async () => {
    seed()
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/projects/1/sessions': () => jsonResponse([]) }))
    await router.replace('/projects/1?sessao=a&aba=rotinas')
    const wrapper = await mountView()
    await wrapper.get('[data-test="project-tab-conversas"]').trigger('keydown', { key: 'ArrowRight' })
    await flushPromises()
    expect(router.currentRoute.value.query).toMatchObject({ visao: 'git', sessao: 'a', aba: 'rotinas' })
    await wrapper.get('[data-test="project-tab-git"]').trigger('keydown', { key: 'End' })
    await flushPromises()
    expect(wrapper.get('[data-test="project-tab-organizacao"]').attributes('aria-selected')).toBe('true')
    expect(wrapper.find('[data-test="scm-section"]').exists()).toBe(false)
    router.back()
    await flushPromises()
    expect(wrapper.get('[data-test="project-tab-git"]').attributes('aria-selected')).toBe('true')
    await wrapper.get('[data-test="project-tab-git"]').trigger('keydown', { key: 'Home' })
    await flushPromises()
    expect(wrapper.get('[data-test="project-tab-conversas"]').attributes('aria-selected')).toBe('true')
  })

  it('resume Git carregado sem consulta extra e mantém ações secundárias no menu', async () => {
    seed()
    useGitStore().set(1, [makeGitRepo({ changed: { staged: 1, unstaged: 2, untracked: 0 }, ahead: 10 })])
    const fetchMock = routeFetch({ 'GET /api/projects/1/sessions': () => jsonResponse([]) })
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = await mountView()
    expect(wrapper.get('[data-test="project-git-summary"]').text()).toContain('3 alterações')
    expect(wrapper.get('[data-test="project-git-summary"]').text()).toContain('10 para enviar')
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes('/git'))).toBe(false)
    expect(wrapper.find('[data-test="rename"]').exists()).toBe(false)
    await wrapper.get('[data-test="project-actions"]').trigger('click')
    expect(wrapper.get('[data-test="rename"]').text()).toBe('Renomear')
  })

  it('abre detalhes sem esperar resumo e compartilha o resultado com a barra lateral', async () => {
    await router.replace('/projects/1?visao=git')
    seed()
    let release!: (r: Response) => void
    const fetchMock = routeFetch({
      'GET /api/projects/1/sessions': () => jsonResponse([]),
      'GET /api/projects/1/git': () => new Promise<Response>(() => {}),
      'GET /api/projects/1/git/details': () => new Promise<Response>(resolve => { release = resolve }),
    })
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = await mountView()
    expect(wrapper.find('[data-test="git-loading"]').exists()).toBe(true)
    expect(fetchMock.mock.calls.filter(c => String(c[0]).endsWith('/git/details'))).toHaveLength(1)
    expect(fetchMock.mock.calls.some(c => String(c[0]).endsWith('/git'))).toBe(false)
    release(jsonResponse({ repos: [makeRepoDetails({ branch: 'nova' })], limit_reached: true }))
    await flushPromises()
    expect(wrapper.find('[data-test="scm-repo"]').exists()).toBe(true)
    expect(useGitStore().reposFor(1)[0]!.branch).toBe('nova')
    expect(useGitStore().limitReached(1)).toBe(true)
  })

  it('erro inicial dos detalhes oferece nova tentativa sem depender do resumo', async () => {
    await router.replace('/projects/1?visao=git')
    seed()
    let fail = true
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/projects/1/sessions': () => jsonResponse([]),
      'GET /api/projects/1/git/details': () => fail ? jsonResponse({ detail: 'Falha ao ler Git.' }, 500) : jsonResponse({ repos: [], limit_reached: false }),
    }))
    const wrapper = await mountView()
    expect(wrapper.get('[data-test="git-error"]').text()).toContain('Falha ao ler Git.')
    fail = false
    await wrapper.get('[data-test="git-retry"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('sem repositório git')
    expect(wrapper.find('[data-test="git-error"]').exists()).toBe(false)
  })

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

  it('abre a organização dentro da aba do projeto', async () => {
    seed()
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/projects/1/sessions': () => jsonResponse([]) }))
    const wrapper = await mountView()
    await wrapper.get('[data-test="project-tab-organizacao"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/projects/1')
    expect(router.currentRoute.value.query.visao).toBe('organizacao')
    expect(wrapper.findAll('h1')).toHaveLength(1)
    expect(wrapper.find('[data-test="new-agent"]').exists()).toBe(true)
  })

  it('não lista as conversas descartadas', async () => {
    seed()
    vi.stubGlobal(
      'fetch',
      routeFetch({
        'GET /api/projects/1/sessions': () =>
          jsonResponse([
            makeSession({ session_id: 'a', title: 'Aberta', state: 'idle' }),
            makeSession({ session_id: 'd', title: 'Sumida', state: 'idle', mark: 'discarded' }),
          ]),
      }),
    )
    const wrapper = await mountView()
    expect(wrapper.findAll('[data-test="row-link"]').map((r) => r.text())).toEqual(['Aberta'])
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

  it('separa finalizadas sem perder as linhas de conversa', async () => {
    seed()
    const now = Date.now() / 1000
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/projects/1/sessions': () => jsonResponse([
      makeSession({ session_id: 'a', title: 'Hoje', last_activity_at: now }),
      makeSession({ session_id: 'b', title: 'Velha', last_activity_at: now - 30 * 86400, display_state: 'finished' }),
    ]) }))
    const wrapper = await mountView()

    expect(wrapper.findAll('[data-test="row-link"]').map((r) => r.text())).toEqual(['Hoje'])
    await wrapper.get('[data-test="filter-finished"]').trigger('click')
    expect(wrapper.findAll('[data-test="row-link"]').map((r) => r.text())).toEqual(['Velha'])
  })

  it('sem conversas mostra a orientação para começar uma', async () => {
    seed()
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/projects/1/sessions': () => jsonResponse([]) }))
    const wrapper = await mountView()

    expect(wrapper.text()).toContain('Nenhuma conversa em aberto neste filtro.')
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

    await wrapper.get('[data-test="project-actions"]').trigger('click')
    await wrapper.find('[data-test="remove"]').trigger('click')
    const dialog = wrapper.find('[data-test="confirm-remove"]')
    expect(dialog.exists()).toBe(true)
    expect(dialog.text()).toContain('A pasta e as conversas não são apagadas')
    expect(fetchMock).not.toHaveBeenCalledWith('/api/projects/1', expect.objectContaining({ method: 'DELETE' }))

    await dialog.find('[data-test="confirm-remove-cancel"]').trigger('click')
    expect(wrapper.find('[data-test="confirm-remove"]').exists()).toBe(false)

    await wrapper.get('[data-test="project-actions"]').trigger('click')
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

    await wrapper.get('[data-test="project-actions"]').trigger('click')
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
    await wrapper.get('[data-test="project-actions"]').trigger('click')
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
    await wrapper.get('[data-test="project-actions"]').trigger('click')
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
    await wrapper.get('[data-test="project-actions"]').trigger('click')
    await wrapper.find('[data-test="sync"]').trigger('click')
    await flushPromises()
    expect(list).toHaveBeenCalledTimes(1)
    expect(useProjectsStore(pinia).byId(1)?.hidden_sessions).toBe(2)
  })

  it('confirmação de remoção: foco vai para Cancelar, Esc fecha e devolve o foco ao menu', async () => {
    seed()
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/projects/1/sessions': () => jsonResponse([]) }))
    const wrapper = mount(ProjectView, { props: { id: 1 }, attachTo: document.body, global: { plugins: [pinia, router] } })
    await flushPromises()
    await wrapper.get('[data-test="project-actions"]').trigger('click')
    await wrapper.find('[data-test="remove"]').trigger('click')
    await flushPromises()
    expect(document.activeElement).toBe(wrapper.find('[data-test="confirm-remove-cancel"]').element)
    await wrapper.find('[data-test="confirm-remove"]').trigger('keydown', { key: 'Escape' })
    await flushPromises()
    expect(wrapper.find('[data-test="confirm-remove"]').exists()).toBe(false)
    expect(document.activeElement).toBe(wrapper.find('[data-test="project-actions"]').element)
    wrapper.unmount()
  })

  it('avisa quando o projeto tem mais de 50 repositórios', async () => {
    await router.replace('/projects/1?visao=git')
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
    await router.replace('/projects/1?visao=git')
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
    const branch = wrapper.find('[data-test="scm-repo"] [data-test="scm-branch"]')
    expect(branch.text()).toBe('abc1234')
    expect(branch.attributes('title')).toBe('HEAD solto')
  })

  it('filtra agrupadores conhecidos, de outro projeto e conversas sem agrupador', async () => {
    seed()
    useGroupsStore(pinia).groups = [makeGroup({ id: 1, project_id: 1, name: 'Checkout' }), makeGroup({ id: 7, project_id: 2, name: 'De outro' })]
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/projects/1/sessions': () => jsonResponse([
      makeSession({ session_id: 'a', title: 'Agrupada', group_id: 1 }),
      makeSession({ session_id: 'b', title: 'Alheia', group_id: 7 }),
      makeSession({ session_id: 'c', title: 'Fantasma', group_id: 99 }),
    ]) }))
    const wrapper = await mountView()
    const rows = () => wrapper.findAll('[data-test="row-link"]').map(row => row.text())
    expect(rows()).toEqual(expect.arrayContaining(['Agrupada', 'Alheia', 'Fantasma']))
    await wrapper.get('[data-test="conversation-group-filter"]').setValue('none')
    expect(rows()).toEqual(['Fantasma'])
    await wrapper.get('[data-test="conversation-group-filter"]').setValue('7')
    expect(rows()).toEqual(['Alheia'])
  })

  it('sem catálogo de agrupadores ainda mostra as conversas e permite criar agrupador', async () => {
    seed()
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/projects/1/sessions': () => jsonResponse([makeSession({ title: 'Agrupada', group_id: 99 })]) }))
    const wrapper = await mountView()
    expect(wrapper.findAll('[data-test="row-link"]').map(row => row.text())).toEqual(['Agrupada'])
    expect(wrapper.text()).toContain('Criar agrupador')
  })

  it('preserva busca e agrupador ao visitar Git e voltar às conversas', async () => {
    seed()
    useGroupsStore().groups = [makeGroup({ id: 1, project_id: 1 })]
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/projects/1/sessions': () => jsonResponse([makeSession({ title: 'Cupom', group_id: 1 })]) }))
    const wrapper = await mountView()
    await wrapper.get('[data-test="conversation-search"]').setValue('Cupom')
    await wrapper.get('[data-test="conversation-group-filter"]').setValue('1')
    await wrapper.get('[data-test="project-tab-git"]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-test="project-tab-conversas"]').trigger('click')
    await flushPromises()
    expect((wrapper.get('[data-test="conversation-search"]').element as HTMLInputElement).value).toBe('Cupom')
    expect((wrapper.get('[data-test="conversation-group-filter"]').element as HTMLSelectElement).value).toBe('1')
    expect(wrapper.findAll('[data-test="row-link"]').map(row => row.text())).toEqual(['Cupom'])
  })

  it('ArrowUp no menu fechado foca a última ação e Esc devolve ao botão', async () => {
    seed()
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/projects/1/sessions': () => jsonResponse([]) }))
    const wrapper = mount(ProjectView, { props: { id: 1 }, attachTo: document.body, global: { plugins: [pinia, router] } })
    await flushPromises()
    const trigger = wrapper.get('[data-test="project-actions"]')
    await trigger.trigger('keydown', { key: 'ArrowUp' })
    await flushPromises()
    expect(document.activeElement).toBe(wrapper.get('[data-test="sync"]').element)
    await wrapper.get('[data-test="sync"]').trigger('keydown', { key: 'Escape' })
    await flushPromises()
    expect(wrapper.find('[role="menu"]').exists()).toBe(false)
    expect(document.activeElement).toBe(trigger.element)
  })

  it('o teclado pula Atualizar enquanto a sincronização está pendente', async () => {
    seed()
    let finish!: (value: Response) => void
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/projects/1/sessions': () => jsonResponse([]),
      'POST /api/projects/1/sync': () => new Promise<Response>(resolve => { finish = resolve }),
    }))
    const wrapper = mount(ProjectView, { props: { id: 1 }, attachTo: document.body, global: { plugins: [pinia, router] } })
    await flushPromises()
    await wrapper.get('[data-test="project-actions"]').trigger('click')
    await wrapper.get('[data-test="sync"]').trigger('click')
    await wrapper.get('[data-test="project-actions"]').trigger('keydown', { key: 'End' })
    expect(document.activeElement).toBe(wrapper.get('[data-test="remove"]').element)
    finish(jsonResponse([]))
    await flushPromises()
  })

  it('mostra o estado git de cada repositório: sincronização, arquivos e commits', async () => {
    await router.replace('/projects/1?visao=git')
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
    const repo = wrapper.find('[data-test="repos"] [data-test="scm-repo"]')
    expect(repo.text()).toContain('loja-online')
    expect(repo.find('[data-test="sync-counts"]').attributes('aria-label')).toBe('0 para baixar, 1 para subir')
    expect(repo.find('[data-test="scm-branch"]').text()).toBe('main*')
    expect(repo.find('[data-test="scm-file"]').text()).toContain('a.py')
    expect(wrapper.find('[data-test="scm-section"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="commits-section"]').exists()).toBe(true)
  })

  it('sem repositório git mostra o estado vazio a partir dos detalhes', async () => {
    await router.replace('/projects/1?visao=git')
    seed()
    const fetchMock = routeFetch({
      'GET /api/projects/1/sessions': () => jsonResponse([]),
      'GET /api/projects/1/git/details': () => jsonResponse({ repos: [], limit_reached: false }),
    })
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = await mountView()
    expect(wrapper.find('[data-test="repos"]').text()).toContain('sem repositório git')
    expect(wrapper.find('[data-test="commits-section"]').exists()).toBe(false)
    expect(fetchMock.mock.calls.filter((c) => String(c[0]).endsWith('/git/details'))).toHaveLength(1)
  })
})

describe('tela do projeto embutido "Sem projeto"', () => {
  function seedScratch() {
    const projects = useProjectsStore(pinia)
    projects.projects = [makeProject({ id: 1, name: 'Sem projeto', kind: 'scratch', path: '/home/vi/.local/share/claudio-maestro/scratch' })]
    projects.loaded = true
  }

  it('mostra só o nome, "Nova sessão" e as conversas', async () => {
    seedScratch()
    const fetchMock = routeFetch({
      'GET /api/projects/1/sessions': () => jsonResponse([makeSession({ session_id: 'a', title: 'Pergunta rápida' })]),
    })
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = await mountView()

    expect(wrapper.find('h1').text()).toBe('Sem projeto')
    expect(wrapper.find('[data-test="new-session"]').exists()).toBe(true)
    expect(wrapper.findAll('[data-test="conversation-row"]')).toHaveLength(1)
    for (const t of ['rename', 'remove', 'open-editor', 'open-organization', 'sync', 'repos']) {
      expect(wrapper.find(`[data-test="${t}"]`).exists(), t).toBe(false)
    }
    expect(wrapper.text()).not.toContain('/home/vi/.local/share/claudio-maestro/scratch')
    expect(wrapper.text()).not.toContain('sem repositório git')
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes('/git'))).toBe(false)
  })

  it('mantém tudo no projeto comum', async () => {
    seed()
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/projects/1/sessions': () => jsonResponse([]) }))
    const wrapper = await mountView()
    await wrapper.get('[data-test="project-actions"]').trigger('click')
    for (const t of ['rename', 'remove', 'open-editor', 'project-tab-organizacao', 'sync', 'new-session']) {
      expect(wrapper.find(`[data-test="${t}"]`).exists(), t).toBe(true)
    }
    expect(wrapper.text()).toContain('/home/vi/dev/loja-online')
  })
})
