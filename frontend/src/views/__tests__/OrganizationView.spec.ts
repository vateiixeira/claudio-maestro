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

  it('sem projeto mostra o seletor e lembra o último', async () => {
    const first = await mountAt('/agentes')
    const options = first.wrapper.findAll('[data-test="org-project-option"]')
    expect(options.map((o) => o.text())).toEqual(['Loja', 'API'])
    expect(options[1]!.attributes('href')).toBe('/agentes/2')
    first.wrapper.unmount()

    // Visitar um projeto o grava; a próxima visita sem projeto vai direto para ele.
    const visit = await mountAt('/agentes/2')
    expect(localStorage.getItem('maestro.org.project')).toBe('2')
    visit.wrapper.unmount()

    const again = await mountAt('/agentes')
    expect(again.router.currentRoute.value.fullPath).toBe('/agentes/2')
  })

  it('o projeto embutido não aparece no seletor de projetos nem no seletor de troca', async () => {
    const { wrapper } = await mountAt('/agentes/1')
    expect(wrapper.text()).not.toContain('Sem projeto')
    const switcher = wrapper.findAll('select option').map((o) => o.text())
    expect(switcher).toEqual(expect.arrayContaining(['Loja', 'API']))
    expect(switcher).not.toContain('Sem projeto')
  })

  it('com só o embutido cadastrado diz que não há projeto', async () => {
    useProjectsStore().projects = [makeProject({ id: 77, name: 'Sem projeto', path: '/home/vi/.local/share/claudio-maestro/scratch', kind: 'scratch', position: 99 })]
    const { wrapper } = await mountAt('/agentes')
    expect(wrapper.findAll('[data-test="org-project-option"]')).toHaveLength(0)
    expect(wrapper.text()).toContain('Nenhum projeto ainda')
  })

  it('o embutido não é um projeto da organização: nem pela URL nem como último lembrado', async () => {
    localStorage.setItem('maestro.org.project', '77')
    const { wrapper, router } = await mountAt('/agentes')
    expect(router.currentRoute.value.fullPath).toBe('/agentes')
    expect(wrapper.findAll('[data-test="org-project-option"]')).toHaveLength(2)
    wrapper.unmount()
    const direct = await mountAt('/agentes/77')
    expect(direct.wrapper.find('[data-test="org-project-missing"]').exists()).toBe(true)
    expect(localStorage.getItem('maestro.org.project')).toBe('77')
  })

  it('ignora o último projeto lembrado quando ele não existe mais', async () => {
    localStorage.setItem('maestro.org.project', '99')
    const { wrapper, router } = await mountAt('/agentes')
    expect(router.currentRoute.value.fullPath).toBe('/agentes')
    expect(wrapper.findAll('[data-test="org-project-option"]')).toHaveLength(2)
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
