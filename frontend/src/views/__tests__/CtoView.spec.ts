import { beforeEach, afterEach, expect, it, vi } from 'vitest'
import { mount, flushPromises, enableAutoUnmount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import { createAppRouter } from '../../router'
import CtoView from '../CtoView.vue'
import { useProjectsStore } from '../../stores/projects'
import { useWorkStore } from '../../stores/work'
import { useSessionsStore } from '../../stores/sessions'
import { makeProject, makeSession, routeFetch, jsonResponse } from '../../test/factories'
enableAutoUnmount(afterEach)
beforeEach(() => { setActivePinia(createPinia()); useProjectsStore().projects = [makeProject({ id: 1 }), makeProject({ id: 2 })] })
afterEach(() => vi.unstubAllGlobals())
it('trocar projeto abre o CTO correto e não troca o diretório de uma sessão viva', async () => {
  const fetch = routeFetch({
    'POST /api/projects/1/cto': () => jsonResponse({ session_id: 'cto-one', project_id: 1 }),
    'POST /api/projects/2/cto': () => jsonResponse({ session_id: 'cto-two', project_id: 2 }),
    'GET /api/projects/1/work-mode': () => jsonResponse({ enabled: true, paused: false }),
    'GET /api/projects/2/work-mode': () => jsonResponse({ enabled: false, paused: false }),
    'GET /api/work/runtime': () => jsonResponse({ dispatcher_enabled: false }),
  }); vi.stubGlobal('fetch', fetch)
  const router = createAppRouter(createMemoryHistory()); await router.push('/cto?projeto=1')
  const wrapper = mount(CtoView, { global: { plugins: [router], stubs: { ConversationView: { props: ['id'], template: '<div data-test="cto-conversation">{{ id }}</div>' } } } })
  await flushPromises(); expect(wrapper.get('[data-test="cto-conversation"]').text()).toBe('cto-one')
  const projectOptions = wrapper.get('[data-test="cto-project-options-toggle"]')
  expect(projectOptions.attributes('aria-expanded')).toBe('false')
  await projectOptions.trigger('click')
  expect(projectOptions.attributes('aria-expanded')).toBe('true')
  expect(wrapper.get('[data-test="cto-project-options"]').classes()).toContain('mobile-expanded')
  await wrapper.get('select').setValue('2'); await flushPromises()
  expect(wrapper.get('[data-test="cto-conversation"]').text()).toBe('cto-two')
  expect(fetch.mock.calls.some(call => call[1]?.method === 'PATCH')).toBe(false)
})

it('resposta atrasada de pausa não altera o modo do projeto recém-aberto', async () => {
  let pause!: (value: Response) => void
  vi.stubGlobal('fetch', routeFetch({
    'POST /api/projects/1/cto': () => jsonResponse({ session_id: 'cto-one' }),
    'POST /api/projects/2/cto': () => jsonResponse({ session_id: 'cto-two' }),
    'GET /api/projects/1/work-mode': () => jsonResponse({ enabled: true, paused: false }),
    'GET /api/projects/2/work-mode': () => jsonResponse({ enabled: true, paused: false }),
    'GET /api/work/runtime': () => jsonResponse({ dispatcher_enabled: true }),
    'POST /api/projects/1/work-mode': () => new Promise<Response>(resolve => { pause = resolve }),
  }))
  const router = createAppRouter(createMemoryHistory()); await router.push('/cto?projeto=1')
  const wrapper = mount(CtoView, { global: { plugins: [router], stubs: { ConversationView: true } } })
  await flushPromises()
  await wrapper.findAll('button').find(b => b.text() === 'Pausar fila')!.trigger('click')
  await wrapper.get('select').setValue('2'); await flushPromises()
  pause(jsonResponse({ enabled: true, paused: true })); await flushPromises()
  expect(wrapper.text()).toContain('Coordenação ativa')
  expect(wrapper.text()).not.toContain('Fila pausada')
})

it('limpar projeto enquanto abre uma conversa pendente volta à escolha de projeto', async () => {
  let release!: (value: Response) => void
  vi.stubGlobal('fetch', routeFetch({
    'POST /api/projects/1/cto': () => new Promise<Response>(resolve => { release = resolve }),
    'GET /api/projects/1/work-mode': () => jsonResponse({ enabled: true, paused: false }),
    'GET /api/work/runtime': () => jsonResponse({ dispatcher_enabled: false }),
  }))
  const router = createAppRouter(createMemoryHistory()); await router.push('/cto?projeto=1')
  const wrapper = mount(CtoView, { global: { plugins: [router], stubs: { ConversationView: true } } })
  await flushPromises(); expect(wrapper.text()).toContain('Abrindo conversa do CTO')
  await wrapper.get('select').setValue(''); await flushPromises()
  expect(wrapper.text()).toContain('Escolha onde o trabalho acontece')
  expect(wrapper.text()).not.toContain('Abrindo conversa do CTO')
  release(jsonResponse({ session_id: 'old-cto' })); await flushPromises()
  expect(wrapper.text()).toContain('Um CTO por projeto'); expect(wrapper.text()).toContain('Conversas em andamento')
  expect(router.currentRoute.value.fullPath).toBe('/cto')
})

function mountList(setup: () => void) {
  setup()
  const fetch = routeFetch({ 'GET /api/work/runtime': () => jsonResponse({ dispatcher_enabled: true }) }); vi.stubGlobal('fetch', fetch)
  const router = createAppRouter(createMemoryHistory())
  return router.push('/cto').then(async () => { const wrapper = mount(CtoView, { global: { plugins: [router], stubs: { ConversationView: true } } }); await flushPromises(); return { wrapper, router, fetch } })
}
const NOW = Math.floor(Date.now() / 1000)

it('sem projeto, mostra as conversas abertas no topo por atividade, mesmo com uma só, e não cria nenhuma', async () => {
  const { wrapper, fetch } = await mountList(() => {
    useProjectsStore().projects = [makeProject({ id: 1, name: 'alfa' }), makeProject({ id: 2, name: 'beta' }), makeProject({ id: 3, name: 'gama' }), makeProject({ id: 4, name: 'delta' })]
    useWorkStore().coordinators = { 1: 'c1', 2: 'c2', 3: 'c3' }
    useSessionsStore().setForProject(1, [makeSession({ session_id: 'c1', project_id: 1, last_activity_at: NOW - 7200, display_state: 'waiting' })])
    useSessionsStore().setForProject(2, [makeSession({ session_id: 'c2', project_id: 2, last_activity_at: NOW - 60 * 5, display_state: 'running' })])
    useSessionsStore().setForProject(3, [makeSession({ session_id: 'c3', project_id: 3, finished: true, display_state: 'finished' })])
  })
  const open = wrapper.findAll('[data-test="cto-open"] [data-test="cto-item"]')
  expect(open.map(item => item.get('.cto-name').text())).toEqual(['beta', 'alfa'])
  expect(open[0]!.text()).toContain('Em execução'); expect(open[0]!.text()).toContain('há 5 min')
  expect(open[1]!.text()).toContain('CTO disponível'); expect(open[1]!.text()).toContain('há 2 h')
  const others = wrapper.findAll('[data-test="cto-others"] [data-test="cto-item"]')
  expect(others.map(item => item.get('.cto-name').text())).toEqual(['gama', 'delta'])
  expect(fetch.mock.calls.some(call => call[1]?.method === 'POST')).toBe(false)
})

it('com uma única conversa aberta a lista aparece e clicar abre o projeto', async () => {
  const { wrapper, router } = await mountList(() => {
    useProjectsStore().projects = [makeProject({ id: 1, name: 'alfa' }), makeProject({ id: 2, name: 'beta' })]
    useWorkStore().coordinators = { 2: 'c2' }
    useSessionsStore().setForProject(2, [makeSession({ session_id: 'c2', project_id: 2 })])
  })
  const open = wrapper.findAll('[data-test="cto-open"] [data-test="cto-item"]')
  expect(open).toHaveLength(1)
  await open[0]!.trigger('click'); await flushPromises()
  expect(router.currentRoute.value.fullPath).toBe('/cto?projeto=2')
})

it('sem conversas abertas só há a lista de projetos, e projeto indisponível fica desabilitado', async () => {
  const { wrapper } = await mountList(() => { useProjectsStore().projects = [makeProject({ id: 1, name: 'alfa' }), makeProject({ id: 2, name: 'beta', available: false })] })
  expect(wrapper.find('[data-test="cto-open"]').exists()).toBe(false)
  const items = wrapper.findAll('[data-test="cto-others"] [data-test="cto-item"]')
  expect(items).toHaveLength(2)
  expect(items[1]!.attributes('disabled')).toBeDefined()
})

it('a lista reage quando o catálogo muda', async () => {
  const { wrapper } = await mountList(() => { useProjectsStore().projects = [makeProject({ id: 1, name: 'alfa' })] })
  expect(wrapper.find('[data-test="cto-open"]').exists()).toBe(false)
  useSessionsStore().setForProject(1, [makeSession({ session_id: 'c1', project_id: 1 })])
  useWorkStore().coordinators = { 1: 'c1' }
  await flushPromises()
  expect(wrapper.findAll('[data-test="cto-open"] [data-test="cto-item"]')).toHaveLength(1)
})

it('conversa aberta em projeto com pasta indisponível aparece desabilitada', async () => {
  const { wrapper } = await mountList(() => {
    useProjectsStore().projects = [makeProject({ id: 1, name: 'alfa', available: false })]
    useWorkStore().coordinators = { 1: 'c1' }
    useSessionsStore().setForProject(1, [makeSession({ session_id: 'c1', project_id: 1 })])
  })
  const open = wrapper.findAll('[data-test="cto-open"] [data-test="cto-item"]')
  expect(open).toHaveLength(1)
  expect(open[0]!.attributes('disabled')).toBeDefined()
  expect(open[0]!.text()).toContain('Pasta indisponível')
})

it.each([
  [{ state: 'idle', display_state: 'waiting', unread: true }, 'CTO disponível'],
  [{ state: 'idle', display_state: 'running', subagents_running: true }, 'Em execução'],
  [{ state: 'awaiting_decision', display_state: 'waiting', pending_kind: 'question' }, 'Aguardando você'],
  [{ state: 'awaiting_decision', display_state: 'waiting', pending_kind: 'plan' }, 'Aguardando você'],
] as const)('lista preserva estado factual do CTO %j', async (state, expected) => {
  const { wrapper } = await mountList(() => {
    useProjectsStore().projects = [makeProject({ id: 1 })]
    useWorkStore().coordinators = { 1: 'c1' }
    useSessionsStore().setForProject(1, [makeSession({ session_id: 'c1', project_id: 1, ...state })])
  })
  expect(wrapper.get('[data-test="cto-item"]').text()).toContain(expected)
})
