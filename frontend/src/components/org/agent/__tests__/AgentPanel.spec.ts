import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import AgentPanel from '../AgentPanel.vue'
import { createAppRouter } from '../../../../router'
import { useOrgStore } from '../../../../stores/org'
import { useProjectsStore } from '../../../../stores/projects'
import { jsonResponse, makeAgent, makeProject, routeFetch } from '../../../../test/factories'
import type { Agent } from '../../../../types/org'

enableAutoUnmount(afterEach)
let pinia: Pinia
beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
})
afterEach(() => vi.unstubAllGlobals())

type Handlers = Parameters<typeof routeFetch>[0]
const FILE = '---\nname: Dev\n---\nTrabalha.\n'

async function mountPanel(path: string, agent: Partial<Agent> = {}, handlers: Handlers = {}) {
  const org = useOrgStore(pinia)
  org.agents = [makeAgent({ id: 1, name: 'CTO' }), makeAgent({ id: 2, slug: 'dev', name: 'Dev', description: 'Faz as tarefas', reports_to: 1, ...agent })]
  const projects = useProjectsStore(pinia)
  projects.projects = [makeProject({ id: 1 })]
  projects.loaded = true
  const fetch = routeFetch({
    'GET /api/agents/2/conversations': () => jsonResponse([]),
    'GET /api/agents/2/definition': () => jsonResponse({ text: FILE, hash: 'h1' }),
    'GET /api/agents/2/memory': () => jsonResponse({ text: 'Lembrar do X.' }),
    'GET /api/agents/2/secrets': () => jsonResponse({ names: [] }),
    'GET /api/agents/2/registry': () => jsonResponse([]),
    'GET /api/agents/2/runs?limit=50': () => jsonResponse([]),
    'GET /api/agents/2/wakeups': () => jsonResponse([]),
    ...handlers,
  })
  vi.stubGlobal('fetch', fetch)
  const router = createAppRouter(createMemoryHistory())
  await router.push(path)
  await router.isReady()
  const wrapper = mount(AgentPanel, { props: { agentId: 2 }, global: { plugins: [pinia, router] } })
  await flushPromises()
  return { wrapper, fetch, router, org }
}

const selected = (w: Awaited<ReturnType<typeof mountPanel>>['wrapper']) =>
  w.findAll('[role="tab"]').filter((t) => t.attributes('aria-selected') === 'true').map((t) => t.attributes('data-test'))

describe('AgentPanel', () => {
  it('abre em Conversa por padrão', async () => {
    const { wrapper } = await mountPanel('/agentes/1?agente=2')
    expect(wrapper.attributes('data-test')).toBe('agent-panel')
    expect(wrapper.attributes('data-agent-id')).toBe('2')
    expect(selected(wrapper)).toEqual(['agent-tab-conversa'])
    expect(wrapper.find('[data-test="agent-main-conversation"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="definition-text"]').exists()).toBe(false)
  })

  it('mostra as seis seções como abas', async () => {
    const { wrapper } = await mountPanel('/agentes/1?agente=2')
    expect(wrapper.find('[role="tablist"]').exists()).toBe(true)
    expect(wrapper.findAll('[role="tab"]').map((t) => t.attributes('data-test'))).toEqual([
      'agent-tab-conversa', 'agent-tab-definicao', 'agent-tab-memoria', 'agent-tab-segredos', 'agent-tab-registro', 'agent-tab-execucoes',
    ])
    expect(wrapper.findAll('[role="tab"]').map((t) => t.text())).toEqual(['Conversa', 'Definição', 'Memória', 'Segredos', 'Registro', 'Execuções'])
    expect(wrapper.get('[role="tabpanel"]').attributes('aria-labelledby')).toBe(wrapper.get('[data-test="agent-tab-conversa"]').attributes('id'))
  })

  it('abre no editor quando a definição está inválida', async () => {
    const { wrapper } = await mountPanel('/agentes/1?agente=2', { definition_error: 'Falta o campo name na linha 2.' })
    expect(selected(wrapper)).toEqual(['agent-tab-definicao'])
    expect(wrapper.find('[data-test="definition-text"]').exists()).toBe(true)
    expect(wrapper.get('[data-test="definition-current-error"]').text()).toContain('Falta o campo name na linha 2.')
    expect(wrapper.get('[data-test="agent-run"]').attributes('disabled')).toBeDefined()
  })

  it('a query aba escolhe a seção e vence o erro de definição', async () => {
    const { wrapper } = await mountPanel('/agentes/1?agente=2&aba=memoria', { definition_error: 'ruim' })
    expect(selected(wrapper)).toEqual(['agent-tab-memoria'])
    expect(wrapper.find('[data-test="memory-text"]').exists()).toBe(true)
  })

  it('aba desconhecida cai no padrão', async () => {
    const { wrapper } = await mountPanel('/agentes/1?agente=2&aba=tarefas')
    expect(selected(wrapper)).toEqual(['agent-tab-conversa'])
  })

  it('trocar de seção atualiza a query sem perder o agente', async () => {
    const { wrapper, router } = await mountPanel('/agentes/1?agente=2')
    await wrapper.get('[data-test="agent-tab-registro"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.query).toEqual({ agente: '2', aba: 'registro' })
    expect(selected(wrapper)).toEqual(['agent-tab-registro'])
    expect(wrapper.find('[data-test="items-empty"]').exists()).toBe(true)
    await wrapper.get('[data-test="agent-tab-execucoes"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-test="runs-empty"]').exists()).toBe(true)
  })

  it('setas movem entre as abas', async () => {
    const { wrapper, router } = await mountPanel('/agentes/1?agente=2')
    await wrapper.get('[data-test="agent-tab-conversa"]').trigger('keydown', { key: 'ArrowRight' })
    await flushPromises()
    expect(router.currentRoute.value.query.aba).toBe('definicao')
    await wrapper.get('[data-test="agent-tab-definicao"]').trigger('keydown', { key: 'End' })
    await flushPromises()
    expect(router.currentRoute.value.query.aba).toBe('execucoes')
  })

  it('rascunho sobrevive à troca de seção', async () => {
    const { wrapper } = await mountPanel('/agentes/1?agente=2&aba=definicao')
    await wrapper.get('[data-test="definition-text"]').setValue('meu rascunho do AGENT.md')
    await wrapper.get('[data-test="agent-tab-memoria"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-test="definition-text"]').exists()).toBe(false)
    await wrapper.get('[data-test="memory-text"]').setValue('meu rascunho da memória')
    await wrapper.get('[data-test="agent-tab-definicao"]').trigger('click')
    await flushPromises()
    expect(wrapper.get<HTMLTextAreaElement>('[data-test="definition-text"]').element.value).toBe('meu rascunho do AGENT.md')
    await wrapper.get('[data-test="agent-tab-memoria"]').trigger('click')
    await flushPromises()
    expect(wrapper.get<HTMLTextAreaElement>('[data-test="memory-text"]').element.value).toBe('meu rascunho da memória')
  })

  it('a aba com rascunho avisa que há alterações não salvas', async () => {
    const { wrapper } = await mountPanel('/agentes/1?agente=2&aba=definicao')
    expect(wrapper.get('[data-test="agent-tab-definicao"]').text()).not.toContain('não salvo')
    await wrapper.get('[data-test="definition-text"]').setValue('mudou')
    expect(wrapper.get('[data-test="agent-tab-definicao"]').text()).toContain('não salvo')
  })

  it('o cabeçalho mostra nome, estado, descrição, chefe e modelo', async () => {
    const { wrapper, router } = await mountPanel('/agentes/1?agente=2', { model: 'sonnet', effort: 'high' })
    expect(wrapper.get('h2').text()).toBe('Dev')
    expect(wrapper.get('[data-test="agent-state"]').attributes('data-state')).toBe('idle')
    expect(wrapper.get('[data-test="agent-description"]').text()).toBe('Faz as tarefas')
    expect(wrapper.get('[data-test="agent-model"]').text()).toBe('Sonnet')
    expect(wrapper.get('[data-test="agent-effort"]').text()).toBe('high')
    const boss = wrapper.get('[data-test="agent-boss-link"]')
    expect(boss.text()).toBe('CTO')
    await boss.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.fullPath).toBe('/agentes/1?agente=1')
  })

  it('sem modelo nem chefe não mostra chips nem link', async () => {
    const { wrapper } = await mountPanel('/agentes/1?agente=2', { reports_to: null })
    expect(wrapper.find('[data-test="agent-model"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="agent-effort"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="agent-boss-link"]').exists()).toBe(false)
  })

  it('excluir volta para a árvore', async () => {
    const { wrapper, router, org } = await mountPanel('/agentes/1?agente=2&aba=definicao', {}, { 'DELETE /api/agents/2': () => jsonResponse(undefined, 204) })
    await wrapper.get('[data-test="agent-delete"]').trigger('click')
    await wrapper.get('[data-test="confirm-ok"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.fullPath).toBe('/agentes/1')
    expect(org.byId(2)).toBeUndefined()
  })
})
