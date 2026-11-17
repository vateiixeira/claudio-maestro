import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import OrganizationView from '../OrganizationView.vue'
import { createAppRouter } from '../../router'
import { useOrgStore } from '../../stores/org'
import { useProjectsStore } from '../../stores/projects'
import { jsonResponse, makeAgent, makeProject, routeFetch } from '../../test/factories'

enableAutoUnmount(afterEach)
let pinia: Pinia

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  localStorage.removeItem('maestro.org.project')
  useProjectsStore().projects = [makeProject({ id: 1, name: 'Loja' }), makeProject({ id: 2, name: 'API' }), makeProject({ id: 77, name: 'Sem projeto', path: '/home/vi/.local/share/claudio-maestro/scratch', kind: 'scratch', position: 99 })]
  useProjectsStore().loaded = true
  useOrgStore().loaded = true
})
afterEach(() => vi.unstubAllGlobals())

async function mountAt(path: string) {
  const router = createAppRouter(createMemoryHistory())
  await router.push(path)
  await router.isReady()
  const projectId = router.currentRoute.value.params.projectId
  const wrapper = mount(OrganizationView, {
    props: { projectId: projectId ? Number(projectId) : undefined },
    global: { plugins: [pinia, router] },
    attachTo: document.body,
  })
  await flushPromises()
  return { wrapper, router }
}

describe('OrganizationView', () => {
  it('embutida preserva a aba do projeto ao selecionar agente e voltar, sem repetir cabeçalho', async () => {
    useOrgStore().agents = [makeAgent({ id: 1 })]
    const router = createAppRouter(createMemoryHistory())
    await router.push('/projects/1?visao=organizacao&sessao=abc&aba=rotinas')
    const wrapper = mount(OrganizationView, { props: { projectId: 1, embedded: true }, global: { plugins: [pinia, router] } })
    await flushPromises()
    expect(wrapper.find('h1').exists()).toBe(false)
    expect(wrapper.find('[data-test="org-project-select"]').exists()).toBe(false)
    await wrapper.get('[data-test="org-node-button"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.query).toMatchObject({ visao: 'organizacao', sessao: 'abc', agente: '1' })
    expect(router.currentRoute.value.query.aba).toBeUndefined()
    await wrapper.get('[data-test="org-back"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.query).toEqual({ visao: 'organizacao', sessao: 'abc' })
  })

  it('empilha a árvore quando o projeto divide espaço com uma conversa', async () => {
    vi.stubGlobal('matchMedia', () => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() }))
    const router = createAppRouter(createMemoryHistory())
    await router.push('/projects/1?visao=organizacao&sessao=abc')
    const wrapper = mount(OrganizationView, { props: { projectId: 1, embedded: true, compact: true }, global: { plugins: [pinia, router] } })
    await flushPromises()
    expect(wrapper.get('[data-test="org-tree"]').element.tagName).toBe('DETAILS')
    await wrapper.setProps({ compact: false })
    expect(wrapper.get('[data-test="org-tree"]').element.tagName).toBe('ASIDE')
  })

  it('sem projeto mostra a visão geral, sem pular para o último projeto visto', async () => {
    localStorage.setItem('maestro.org.project', '2')
    const { wrapper, router } = await mountAt('/agentes')
    expect(router.currentRoute.value.fullPath).toBe('/agentes')
    expect(wrapper.find('[data-test="org-overview"]').exists()).toBe(true)
    const options = wrapper.findAll('[data-test="org-project-option"]')
    expect(options.map((o) => o.text())).toEqual([expect.stringContaining('Loja'), expect.stringContaining('API')])
    expect(options[1]!.attributes('href')).toBe('/agentes/2')
  })

  it('visitar um projeto não grava mais o último projeto', async () => {
    const visit = await mountAt('/agentes/2')
    expect(localStorage.getItem('maestro.org.project')).toBeNull()
    visit.wrapper.unmount()
  })

  it('o projeto embutido não aparece no seletor de projetos nem no seletor de troca', async () => {
    const { wrapper } = await mountAt('/agentes/1')
    expect(wrapper.text()).not.toContain('Sem projeto')
    const switcher = wrapper.findAll('select option').map((o) => o.text())
    expect(switcher).toEqual(expect.arrayContaining(['Loja', 'API']))
    expect(switcher).not.toContain('Sem projeto')
  })

  it('com erro ao carregar os projetos mostra o erro e tenta de novo, em vez de Nenhum projeto ainda', async () => {
    useProjectsStore().projects = []
    useProjectsStore().loadError = 'Sem conexão'
    const fetch = routeFetch({ 'GET /api/projects': () => jsonResponse([makeProject({ id: 1, name: 'Loja' })]) })
    vi.stubGlobal('fetch', fetch)
    const { wrapper } = await mountAt('/agentes')
    expect(wrapper.get('[data-test="org-projects-error"]').text()).toContain('Sem conexão')
    expect(wrapper.text()).not.toContain('Nenhum projeto ainda')
    await wrapper.get('[data-test="org-projects-retry"]').trigger('click')
    await flushPromises()
    expect(fetch.mock.calls.some((c) => c[0] === '/api/projects')).toBe(true)
    expect(wrapper.find('[data-test="org-projects-error"]').exists()).toBe(false)
  })

  it('projetos em erro e agentes ainda não carregados: tentar de novo traz os projetos e os agentes', async () => {
    useProjectsStore().projects = []
    useProjectsStore().loadError = 'Sem conexão'
    useOrgStore().loaded = false
    const fetch = routeFetch({
      'GET /api/projects': () => jsonResponse([makeProject({ id: 1, name: 'Loja' })]),
      'GET /api/agents': () => jsonResponse([makeAgent({ id: 1, project_id: 1 })]),
    })
    vi.stubGlobal('fetch', fetch)
    const { wrapper } = await mountAt('/agentes')
    await wrapper.get('[data-test="org-projects-retry"]').trigger('click')
    await flushPromises()
    expect(fetch.mock.calls.some((c) => c[0] === '/api/agents')).toBe(true)
    expect(wrapper.find('[role="status"]').exists()).toBe(false)
    expect(wrapper.findAll('[data-test="org-overview-agent"]')).toHaveLength(1)
  })

  it('com só o embutido cadastrado diz que não há projeto', async () => {
    useProjectsStore().projects = [makeProject({ id: 77, name: 'Sem projeto', path: '/home/vi/.local/share/claudio-maestro/scratch', kind: 'scratch', position: 99 })]
    const { wrapper } = await mountAt('/agentes')
    expect(wrapper.findAll('[data-test="org-project-option"]')).toHaveLength(0)
    expect(wrapper.text()).toContain('Nenhum projeto ainda')
  })

  it('o embutido não é um projeto da organização: nem pela URL nem na visão geral', async () => {
    const { wrapper } = await mountAt('/agentes')
    expect(wrapper.text()).not.toContain('Sem projeto')
    wrapper.unmount()
    const direct = await mountAt('/agentes/77')
    expect(direct.wrapper.find('[data-test="org-project-missing"]').exists()).toBe(true)
  })

  it('com projeto lista a árvore e as abas', async () => {
    useOrgStore(pinia).agents = [makeAgent({ id: 1, project_id: 1 }), makeAgent({ id: 5, slug: 'x', name: 'De outro', project_id: 2 })]
    const { wrapper } = await mountAt('/agentes/1')
    expect(wrapper.get('h1').text()).toBe('Loja')
    expect(wrapper.get('[data-test="org-tree"]').findAll('[data-test="org-node"]')).toHaveLength(1)
    const tabs = wrapper.get('[role="tablist"]')
    expect(tabs.findAll('[role="tab"]').map((t) => t.text())).toEqual(['Tarefas', 'Rotinas', 'Execuções'])
    expect(wrapper.find('[data-test="tasks-tab"]').exists()).toBe(true)
    expect(wrapper.get('[data-test="org-tab-tarefas"]').attributes('aria-selected')).toBe('true')
    await wrapper.get('[data-test="org-tab-rotinas"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-test="routines-tab"]').exists()).toBe(true)
    expect(wrapper.get('[data-test="org-tab-rotinas"]').attributes('aria-selected')).toBe('true')
  })

  it('o seletor de projeto tem o nome acessível Trocar de projeto', async () => {
    const { wrapper } = await mountAt('/agentes/1')
    const select = wrapper.get('[data-test="org-project-select"]')
    expect(select.attributes('aria-label')).toBe('Trocar de projeto')
    expect(wrapper.get('[data-test="org-project-chip"]').text()).toContain('Trocar')
  })

  it('lê as rotinas do projeto e as execuções de cada agente uma vez só', async () => {
    useOrgStore(pinia).agents = [makeAgent({ id: 10, project_id: 2 }), makeAgent({ id: 11, slug: 'b', name: 'B', project_id: 2, reports_to: 10 }), makeAgent({ id: 12, slug: 'c', name: 'C', project_id: 1 })]
    const fetch = routeFetch({
      'GET /api/routines?project_id=2': () => jsonResponse([]),
      'GET /api/agents/10/runs?limit=50': () => jsonResponse([]),
      'GET /api/agents/11/runs?limit=50': () => jsonResponse([]),
    })
    vi.stubGlobal('fetch', fetch)
    await mountAt('/agentes/2')
    await flushPromises()
    const urls = fetch.mock.calls.map((c) => c[0])
    expect(urls.filter((u) => u === '/api/routines?project_id=2')).toHaveLength(1)
    expect(urls.filter((u) => u === '/api/agents/10/runs?limit=50')).toHaveLength(1)
    expect(urls.filter((u) => u === '/api/agents/11/runs?limit=50')).toHaveLength(1)
    expect(urls.some((u) => String(u).includes('/api/agents/12/runs'))).toBe(false)
  })

  it('um agente novo na loja também tem as execuções lidas', async () => {
    useOrgStore(pinia).agents = [makeAgent({ id: 10, project_id: 2 })]
    const fetch = routeFetch({
      'GET /api/routines?project_id=2': () => jsonResponse([]),
      'GET /api/agents/10/runs?limit=50': () => jsonResponse([]),
      'GET /api/agents/11/runs?limit=50': () => jsonResponse([]),
    })
    vi.stubGlobal('fetch', fetch)
    await mountAt('/agentes/2')
    useOrgStore(pinia).upsertAgent(makeAgent({ id: 11, slug: 'b', name: 'B', project_id: 2, reports_to: 10 }))
    await flushPromises()
    const urls = fetch.mock.calls.map((c) => c[0])
    expect(urls.filter((u) => u === '/api/agents/11/runs?limit=50')).toHaveLength(1)
    expect(urls.filter((u) => u === '/api/agents/10/runs?limit=50')).toHaveLength(1)
  })

  it('a aba vem da query e uma aba inválida cai em Tarefas', async () => {
    useOrgStore(pinia).agents = [makeAgent({ id: 1 })]
    const ok = await mountAt('/agentes/1?aba=execucoes')
    expect(ok.wrapper.find('[data-test="runs-tab"]').exists()).toBe(true)
    ok.wrapper.unmount()
    const bad = await mountAt('/agentes/1?aba=xyz')
    expect(bad.wrapper.find('[data-test="tasks-tab"]').exists()).toBe(true)
  })

  it('query agente abre o painel', async () => {
    useOrgStore(pinia).agents = [makeAgent({ id: 1 }), makeAgent({ id: 2, slug: 'dev', name: 'Dev', reports_to: 1 })]
    const { wrapper, router } = await mountAt('/agentes/1?agente=2')
    expect(wrapper.find('[data-test="agent-panel"]').attributes('data-agent-id')).toBe('2')
    expect(wrapper.find('[role="tablist"][aria-label="Organização"]').exists()).toBe(false)
    await wrapper.get('[data-test="org-back"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.query.agente).toBeUndefined()
    expect(wrapper.find('[data-test="agent-panel"]').exists()).toBe(false)
    expect(wrapper.find('[role="tablist"][aria-label="Organização"]').exists()).toBe(true)
  })

  it('agente da query que não é do projeto mostra aviso em vez do painel', async () => {
    useOrgStore(pinia).agents = [makeAgent({ id: 1 }), makeAgent({ id: 5, slug: 'x', project_id: 2 })]
    const { wrapper } = await mountAt('/agentes/1?agente=5')
    expect(wrapper.find('[data-test="agent-panel"]').exists()).toBe(false)
    expect(wrapper.get('[data-test="org-agent-missing"]').text()).toContain('Agente não encontrado')
  })

  it('novo agente abre o diálogo e navega para a definição', async () => {
    useOrgStore(pinia).agents = [makeAgent({ id: 1 })]
    const created = makeAgent({ id: 9, slug: 'dev', name: 'Dev', reports_to: 1 })
    const fetch = routeFetch({ 'POST /api/agents': () => jsonResponse(created, 201) })
    vi.stubGlobal('fetch', fetch)
    const { wrapper, router } = await mountAt('/agentes/1')
    await wrapper.get('[data-test="new-agent"]').trigger('click')
    await wrapper.get('[data-test="new-name"]').setValue('Dev')
    await wrapper.get('[data-test="confirm-ok"]').trigger('click')
    await flushPromises()
    const body = JSON.parse(String(fetch.mock.calls.find(([, init]) => init?.method === 'POST')![1]!.body))
    expect(body).toMatchObject({ name: 'Dev', slug: 'dev', project_id: 1, reports_to: 1, kind: 'worker' })
    expect(router.currentRoute.value.query).toMatchObject({ agente: '9', aba: 'definicao' })
    expect(wrapper.find('[data-test="new-name"]').exists()).toBe(false)
    expect(useOrgStore(pinia).byId(9)?.name).toBe('Dev')
  })

  it('o botão do CTO abre a conversa principal do agente de topo', async () => {
    useOrgStore(pinia).agents = [makeAgent({ id: 1 }), makeAgent({ id: 2, slug: 'dev', name: 'Dev', reports_to: 1 })]
    vi.stubGlobal('fetch', routeFetch({ 'POST /api/agents/1/main': () => jsonResponse({ session_id: 'conv-1' }) }))
    const { wrapper, router } = await mountAt('/agentes/1')
    await wrapper.get('[data-test="talk-cto"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('session')
    expect(router.currentRoute.value.params.id).toBe('conv-1')
  })

  it('sem agentes não oferece conversar com o CTO', async () => {
    const { wrapper } = await mountAt('/agentes/1')
    expect(wrapper.find('[data-test="talk-cto"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="org-tree-empty"]').exists()).toBe(true)
  })

  it('mostra o erro ao abrir a conversa', async () => {
    useOrgStore(pinia).agents = [makeAgent({ id: 1 })]
    vi.stubGlobal('fetch', routeFetch({ 'POST /api/agents/1/main': () => jsonResponse({ detail: 'Pasta indisponível.' }, 409) }))
    const { wrapper } = await mountAt('/agentes/1')
    await wrapper.get('[data-test="talk-cto"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('Pasta indisponível.')
  })

  it('projeto desconhecido avisa em vez de montar a tela', async () => {
    const { wrapper } = await mountAt('/agentes/77')
    expect(wrapper.get('[data-test="org-project-missing"]').text()).toContain('Projeto não encontrado')
  })

  it('mostra o erro de carga dos agentes', async () => {
    useOrgStore(pinia).error = 'Sem conexão'
    const { wrapper } = await mountAt('/agentes/1')
    expect(wrapper.get('[data-test="org-error"]').text()).toContain('Sem conexão')
  })
})
