import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import { createAppRouter } from '../../../router'
import { useSpecialistsStore } from '../../../stores/specialists'
import { jsonResponse, makeEvent, makeSnapshot, makeSpecialist, makeSpecialistRun, routeFetch } from '../../../test/factories'
import AgentExecutions from '../AgentExecutions.vue'
import AgentExecutionDetail from '../AgentExecutionDetail.vue'

const socket = vi.hoisted(() => ({ sessions: new Map<string, Set<(e: ReturnType<typeof makeEvent>) => void>>(), opens: new Set<() => void>() }))
vi.mock('../../../api/socket', () => ({ useEventSocket: () => ({
  onSession: (id: string, fn: (e: ReturnType<typeof makeEvent>) => void) => { const set = socket.sessions.get(id) ?? new Set(); set.add(fn); socket.sessions.set(id, set); return () => { set.delete(fn); if (!set.size) socket.sessions.delete(id) } },
  onOpen: (fn: () => void) => { socket.opens.add(fn); return () => socket.opens.delete(fn) },
}) }))
function emitRun(event: ReturnType<typeof makeEvent>) { socket.sessions.get('run-live')?.forEach(fn => fn(event)) }
enableAutoUnmount(afterEach)
beforeEach(() => { setActivePinia(createPinia()); socket.sessions.clear(); socket.opens.clear() })
afterEach(() => vi.unstubAllGlobals())
async function setup(runs = [makeSpecialistRun({ id: 10, session_id: 'run-live', outcome: 'running' })], extra: Record<string, () => Response | Promise<Response>> = {}) {
  const store = useSpecialistsStore()
  store.list = [makeSpecialist({ main_session_id: 'main' })]
  const fetch = routeFetch({
    'GET /api/specialists': () => jsonResponse(store.list),
    'GET /api/specialists/1/announcements': () => jsonResponse([{ id: 1, run_id: 9, session_id: 'old', text: 'Confirmei a atualização pelo websocket.', created_at: 1, delivered_at: null }]),
    'GET /api/specialists/1/runs?limit=50': () => jsonResponse(runs),
    'GET /api/sessions/run-live': () => jsonResponse(makeSnapshot({ session_id: 'run-live', state: 'running', seq: 1, items: [{ id: 'text', type: 'text', text: 'Investigando a issue 50', streaming: true, parent_tool_use_id: null }] })),
    'GET /api/sessions/old': () => jsonResponse(makeSnapshot({ session_id: 'old', state: 'idle', items: [{ id: 'conclusion', type: 'tool', tool_use_id: 'done', name: 'mcp__maestro__concluir', input: { resumo: 'Confirmei a atualização pelo websocket.' }, result: null, streaming: false, parent_tool_use_id: null }] })),
    ...extra,
  })
  vi.stubGlobal('fetch', fetch)
  const router = createAppRouter(createMemoryHistory())
  await router.push('/sessions/main')
  const w = mount(AgentExecutions, { props: { agentId: 1, mainSessionId: 'main' }, global: { plugins: [router] } })
  await flushPromises()
  return { w, store, fetch, router }
}
it('abre a subexecução em andamento dentro da conversa e recebe texto sem trocar a rota', async () => {
  const { w, router } = await setup()
  expect(w.get('[data-test="agent-execution-toggle"]').attributes('aria-expanded')).toBe('true')
  expect(w.text()).toContain('Investigando a issue 50')
  emitRun(makeEvent('item.append', { item_id: 'text', text: ': websocket confirmado' }, 2, 'run-live'))
  await flushPromises()
  expect(w.text()).toContain('websocket confirmado')
  expect(router.currentRoute.value.fullPath).toBe('/sessions/main')
  w.unmount()
  expect(socket.sessions.size).toBe(0)
})
it('mostra o resumo próprio da rodada antiga só ao expandir e mantém as mensagens da principal fora das subexecuções', async () => {
  const { w, fetch } = await setup([
    makeSpecialistRun({ id: 9, session_id: 'old', outcome: 'concluded' }),
    makeSpecialistRun({ id: 10, session_id: 'main', message: true, outcome: 'concluded' }),
  ])
  expect(w.findAll('[data-test="agent-execution"]')).toHaveLength(1)
  expect(fetch.mock.calls.some(([url]) => url.endsWith('/sessions/old'))).toBe(false)
  await w.get('[data-test="agent-execution-toggle"]').trigger('click')
  await flushPromises()
  expect(w.text()).toContain('Confirmei a atualização pelo websocket.')
  expect(w.get('[data-test="agent-execution-full"]').attributes('href')).toBe('/sessions/old')
})
it('mostra nova execução por evento sem recarregar a conversa principal e não fecha ao concluir', async () => {
  const { w, store } = await setup([])
  expect(w.text()).toContain('As execuções aparecerão aqui')
  store.applyRun(makeSpecialistRun({ id: 10, session_id: 'run-live', outcome: 'running' }))
  await flushPromises()
  expect(w.text()).toContain('Investigando a issue 50')
  store.applyRun(makeSpecialistRun({ id: 10, session_id: 'run-live', outcome: 'concluded' }))
  await flushPromises()
  expect(w.get('[data-test="agent-execution-toggle"]').attributes('aria-expanded')).toBe('true')
  expect(w.text()).toContain('Concluída')
})
it('não oferece ação de executar comandos no texto da subexecução', async () => {
  const { w } = await setup()
  emitRun(makeEvent('item.append', { item_id: 'text', text: '\n```bash\necho teste\n```' }, 2, 'run-live'))
  await flushPromises()
  expect(w.find('[data-code-run]').exists()).toBe(false)
})

it('preserva eventos recebidos enquanto carrega o retrato da subexecução', async () => {
  let release!: (value: Response) => void
  const waiting = new Promise<Response>(resolve => { release = resolve })
  const { w } = await setup(undefined, { 'GET /api/sessions/run-live': () => waiting })
  emitRun(makeEvent('item.append', { item_id: 'text', text: ' + evento recebido durante o carregamento' }, 2, 'run-live'))
  release(jsonResponse(makeSnapshot({ session_id: 'run-live', state: 'running', seq: 1, items: [{ id: 'text', type: 'text', text: 'Retrato', streaming: true, parent_tool_use_id: null }] })))
  await flushPromises()
  expect(w.text()).toContain('Retrato + evento recebido durante o carregamento')
})
it('recarrega na reconexão e permite tentar novamente após falha sem afetar a principal', async () => {
  let calls = 0
  const { w, router } = await setup(undefined, { 'GET /api/sessions/run-live': () => ++calls === 1
    ? jsonResponse({ detail: 'Falha temporária' }, 503)
    : jsonResponse(makeSnapshot({ session_id: 'run-live', seq: calls, items: [{ id: 'text', type: 'text', text: `Retrato ${calls}`, streaming: false, parent_tool_use_id: null }] })) })
  expect(w.get('[role="alert"]').text()).toContain('Falha temporária')
  await w.get('[role="alert"] button').trigger('click')
  await flushPromises()
  expect(w.text()).toContain('Retrato 2')
  socket.opens.forEach(callback => callback())
  await flushPromises()
  expect(w.text()).toContain('Retrato 3')
  expect(router.currentRoute.value.fullPath).toBe('/sessions/main')
})

it('mantém a rodada em andamento visível no fim mesmo com pendências mais novas', async () => {
  const { w } = await setup([
    ...Array.from({ length: 8 }, (_, i) => makeSpecialistRun({ id: 30 - i, session_id: null, outcome: 'queued', started_at: 200 - i })),
    makeSpecialistRun({ id: 10, session_id: 'run-live', outcome: 'running', started_at: 100 }),
  ])
  const cards = w.findAll('[data-test="agent-execution"]')
  expect(cards).toHaveLength(6)
  expect(cards.at(-1)!.attributes('data-run-id')).toBe('10')
  expect(cards.at(-1)!.text()).toContain('Investigando a issue 50')
})

it('refaz o retrato quando a sessão é reconstruída', async () => {
  let reads = 0
  const { w } = await setup(undefined, { 'GET /api/sessions/run-live': () => jsonResponse(makeSnapshot({ session_id: 'run-live', seq: ++reads === 1 ? 1 : 3, items: [{ id: 'text', type: 'text', text: reads === 1 ? 'Antes da reconstrução' : 'Contexto reconstruído', streaming: false, parent_tool_use_id: null }] })) })
  emitRun(makeEvent('conversation.reset', {}, 2, 'run-live'))
  await flushPromises()
  expect(w.text()).toContain('Contexto reconstruído')
  expect(w.text()).not.toContain('Antes da reconstrução')
})
it('reconstrução recebida durante o carregamento também exige um novo retrato', async () => {
  let release!: (value: Response) => void
  const waiting = new Promise<Response>(resolve => { release = resolve })
  let reads = 0
  const { w } = await setup(undefined, { 'GET /api/sessions/run-live': () => ++reads === 1 ? waiting : jsonResponse(makeSnapshot({ session_id: 'run-live', seq: 3, items: [{ id: 'new', type: 'text', text: 'Após reconstruir', streaming: false, parent_tool_use_id: null }] })) })
  emitRun(makeEvent('conversation.reset', {}, 2, 'run-live'))
  release(jsonResponse(makeSnapshot({ session_id: 'run-live', seq: 1, items: [] })))
  await flushPromises()
  expect(w.text()).toContain('Após reconstruir')
})
it('uma conclusão antiga não oculta a continuação da execução em outro turno', async () => {
  const { w } = await setup(undefined, { 'GET /api/sessions/run-live': () => jsonResponse(makeSnapshot({ session_id: 'run-live', state: 'running', seq: 1, items: [{ id: 'done', type: 'tool', tool_use_id: 'done', name: 'mcp__maestro__concluir', input: { resumo: 'Resultado do turno antigo' }, result: null, streaming: false, parent_tool_use_id: null }] })) })
  expect(w.text()).toContain('Resultado do turno antigo')
  emitRun(makeEvent('item.upsert', { id: 'followup', type: 'user', text: 'Investigue mais' }, 2, 'run-live'))
  emitRun(makeEvent('item.upsert', { id: 'new', type: 'text', text: 'Nova investigação em andamento', streaming: true, parent_tool_use_id: null }, 3, 'run-live'))
  await flushPromises()
  expect(w.text()).toContain('Nova investigação em andamento')
  expect(w.text()).not.toContain('Resultado do turno antigo')
  expect(w.find('[data-test="execution-activity"]').exists()).toBe(false)
})

it('duas visualizações da mesma sessão não aplicam append duas vezes ao objeto compartilhado', async () => {
  const { w } = await setup()
  const second = mount(AgentExecutionDetail, { props: { sessionId: 'run-live' }, global: { stubs: { RouterLink: true } } })
  await flushPromises()
  emitRun(makeEvent('item.upsert', { id: 'text', type: 'text', text: 'A', streaming: true, parent_tool_use_id: null }, 2, 'run-live'))
  emitRun(makeEvent('item.append', { item_id: 'text', text: 'B' }, 3, 'run-live'))
  await flushPromises()
  expect(w.text()).toContain('AB')
  expect(w.text()).not.toContain('ABB')
  expect(second.text()).toContain('AB')
  expect(second.text()).not.toContain('ABB')
})
it('duas rodadas na mesma sessão mantêm seus resultados próprios pelo run_id', async () => {
  const { w, fetch } = await setup([
    makeSpecialistRun({ id: 10, session_id: 'same', outcome: 'concluded' }),
    makeSpecialistRun({ id: 9, session_id: 'same', outcome: 'concluded' }),
  ], { 'GET /api/specialists/1/announcements': () => jsonResponse([
    { id: 2, run_id: 10, session_id: 'same', text: 'Resultado da segunda rodada', created_at: 2, delivered_at: null },
    { id: 1, run_id: 9, session_id: 'same', text: 'Resultado da primeira rodada', created_at: 1, delivered_at: null },
  ]) })
  const cards = w.findAll('[data-test="agent-execution"]')
  for (const card of cards) await card.get('button').trigger('click')
  await flushPromises()
  expect(cards[0]!.text()).toContain('Resultado da primeira rodada')
  expect(cards[0]!.text()).not.toContain('Resultado da segunda rodada')
  expect(cards[1]!.text()).toContain('Resultado da segunda rodada')
  expect(cards[1]!.text()).not.toContain('Resultado da primeira rodada')
  expect(fetch.mock.calls.some(([url]) => url.endsWith('/sessions/same'))).toBe(false)
})
it('não atribui a uma rodada antiga sem resumo o texto atual da sessão compartilhada', async () => {
  const { w, fetch } = await setup([makeSpecialistRun({ id: 42, session_id: 'run-live', outcome: 'concluded' })])
  await w.get('[data-test="agent-execution-toggle"]').trigger('click')
  await flushPromises()
  expect(w.text()).toContain('Esta rodada não tem resumo registrado')
  expect(w.text()).not.toContain('Investigando a issue 50')
  expect(fetch.mock.calls.some(([url]) => url.endsWith('/sessions/run-live'))).toBe(false)
})
