import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { mount, flushPromises, enableAutoUnmount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import CoordinatorAttention from '../CoordinatorAttention.vue'
import { jsonResponse, routeFetch } from '../../../test/factories'
enableAutoUnmount(afterEach)
beforeEach(() => setActivePinia(createPinia()))
afterEach(() => vi.unstubAllGlobals())
const page = { counts: { continuation: 1, queued: 1 }, total: 2, limit: 50, offset: 0, items: [
  { work_item_id: 1, title: 'Coletar Sentry', attempt_id: 11, session_id: 'sentry', kind: 'continuation', can_continue: true, queue_reason: null },
  { work_item_id: 2, title: 'Coletar KBGen', attempt_id: null, session_id: null, kind: 'queued', can_continue: false, queue_reason: { kind: 'global_capacity', work_item_id: 1, blocker_title: 'Coletar Sentry' } },
] }
const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/:pathMatch(.*)*', component: { template: '<div />' } }] })
it('explica continuação sem inventar decisão e fila com bloqueador comprovado', async () => {
  vi.stubGlobal('fetch', routeFetch({ 'GET /api/projects/6/work-overview?limit=50&offset=0': () => jsonResponse(page) }))
  const wrapper = mount(CoordinatorAttention, { props: { projectId: 6 }, global: { plugins: [router] } }); await flushPromises()
  expect(wrapper.text()).toContain('O que precisa de você')
  expect(wrapper.text()).toContain('Parou sem registrar uma entrega')
  expect(wrapper.text()).toContain('Na fila, aguardando Coletar Sentry')
  expect(wrapper.text()).not.toContain('aprovar')
  expect(wrapper.get('[data-test="continue-work"]').attributes('href')).toBe('/tarefas/1#attempt-11')
})
it('sem causa específica não atribui a fila a outro trabalho e CTO ocioso não exige ação', async () => {
  vi.stubGlobal('fetch', routeFetch({ 'GET /api/projects/6/work-overview?limit=50&offset=0': () => jsonResponse({ ...page, counts: { queued: 1 }, items: [{ ...page.items[1], queue_reason: null }] }) }))
  const wrapper = mount(CoordinatorAttention, { props: { projectId: 6 }, global: { plugins: [router] } }); await flushPromises()
  expect(wrapper.text()).toContain('Nenhuma ação pendente para você')
  expect(wrapper.text()).toContain('Na fila, aguardando início')
  expect(wrapper.text()).not.toContain('Sentry')
})
it('descarta resposta antiga ao trocar projeto', async () => {
  let resolve!: (response: Response) => void
  vi.stubGlobal('fetch', routeFetch({
    'GET /api/projects/6/work-overview?limit=50&offset=0': () => new Promise<Response>(done => resolve = done),
    'GET /api/projects/7/work-overview?limit=50&offset=0': () => jsonResponse({ ...page, counts: {}, items: [], total: 0 }),
  }))
  const wrapper = mount(CoordinatorAttention, { props: { projectId: 6 }, global: { plugins: [router] } })
  await wrapper.setProps({ projectId: 7 }); await flushPromises(); resolve(jsonResponse(page)); await flushPromises()
  expect(wrapper.text()).not.toContain('Sentry')
})

it.each([
  ['global_capacity', 'capacidade global'], ['project_capacity', 'capacidade do projeto'], ['resource', 'recurso ocupado'], ['dependency', 'dependência'],
])('explica causa comprovada %s sem inventar bloqueador', async (kind, expected) => {
  vi.stubGlobal('fetch', routeFetch({ 'GET /api/projects/6/work-overview?limit=50&offset=0': () => jsonResponse({ ...page, counts: { queued: 1 }, items: [{ ...page.items[1], queue_reason: { kind, work_item_id: null, blocker_title: null } }] }) }))
  const wrapper = mount(CoordinatorAttention, { props: { projectId: 6 }, global: { plugins: [router] } }); await flushPromises()
  expect(wrapper.text()).toContain(expected)
  expect(wrapper.text()).not.toContain('Sentry')
})

it('mantém resumo curto e permite abrir demais pedidos sem perder atenção antiga', async () => {
  const items = Array.from({ length: 6 }, (_, index) => ({ ...page.items[0], work_item_id: index + 1, title: `Coleta ${index + 1}`, attempt_id: index + 11 }))
  vi.stubGlobal('fetch', routeFetch({ 'GET /api/projects/6/work-overview?limit=50&offset=0': () => jsonResponse({ ...page, counts: { continuation: 6 }, items, total: 6 }) }))
  const wrapper = mount(CoordinatorAttention, { props: { projectId: 6 }, global: { plugins: [router] } }); await flushPromises()
  expect(wrapper.findAll('[data-test="continue-work"]')).toHaveLength(3)
  await wrapper.get('[data-test="more-attention"]').trigger('click')
  expect(wrapper.findAll('[data-test="continue-work"]')).toHaveLength(6)
})

it('pedido nativo oferece resposta na conversa exata sem inferir tipo nem abrir continuação', async () => {
  vi.stubGlobal('fetch', routeFetch({ 'GET /api/projects/6/work-overview?limit=50&offset=0': () => jsonResponse({ ...page, counts: { permission: 1 }, total: 1, items: [{ ...page.items[0], kind: 'permission', can_continue: false }] }) }))
  const wrapper = mount(CoordinatorAttention, { props: { projectId: 6 }, global: { plugins: [router] } }); await flushPromises()
  expect(wrapper.text()).toContain('Pedido pendente na execução')
  expect(wrapper.text()).toContain('Responder na conversa')
  expect(wrapper.find('[data-test="continue-work"]').exists()).toBe(false)
  expect(wrapper.findAll('a').find(link => link.text() === 'Responder na conversa')?.attributes('href')).toBe('/sessions/sentry')
})

it('resumo compacto mantém primeira ação e permite expandir contexto sem duplicar CTA', async () => {
  vi.stubGlobal('fetch', routeFetch({ 'GET /api/projects/6/work-overview?limit=50&offset=0': () => jsonResponse(page) }))
  const wrapper = mount(CoordinatorAttention, { props: { projectId: 6 }, global: { plugins: [router] } }); await flushPromises()
  const toggle = wrapper.get('[data-test="attention-details-toggle"]')
  expect(toggle.attributes('aria-expanded')).toBe('false')
  expect(wrapper.findAll('[data-test="continue-work"]')).toHaveLength(1)
  expect(wrapper.get('[data-test="continue-work"]').attributes('href')).toBe('/tarefas/1#attempt-11')
  await toggle.trigger('click')
  expect(toggle.attributes('aria-expanded')).toBe('true')
  expect(wrapper.findAll('[data-test="continue-work"]')).toHaveLength(1)
})
