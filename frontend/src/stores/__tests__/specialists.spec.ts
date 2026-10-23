import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useSpecialistsStore } from '../specialists'
import { jsonResponse, makeSpecialist, makeSpecialistNotice, makeSpecialistRun, routeFetch } from '../../test/factories'
import { EventSocket, type SocketLike } from '../../api/socket'
import { bindRealtime } from '../realtime'

beforeEach(() => setActivePinia(createPinia()))
afterEach(() => vi.unstubAllGlobals())

describe('specialists store', () => {
  it('carrega a lista e acha por id', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/specialists': () => jsonResponse([makeSpecialist(), makeSpecialist({ id: 2, slug: 'filmes', name: 'Filmes' })]) }))
    const store = useSpecialistsStore()
    await store.load()
    expect(store.list.map((s) => s.name)).toEqual(['Sentry', 'Filmes'])
    expect(store.byId(2)?.slug).toBe('filmes')
    expect(store.byId(99)).toBeUndefined()
    expect(store.loaded).toBe(true)
  })

  it('guarda a mensagem quando a lista falha', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/specialists': () => jsonResponse({ detail: 'Quebrou.' }, 500) }))
    const store = useSpecialistsStore()
    await store.load()
    expect(store.error).toBe('Quebrou.')
  })

  it('cria, atualiza e remove', async () => {
    const created = makeSpecialist({ id: 5, slug: 'novo', name: 'Novo' })
    vi.stubGlobal('fetch', routeFetch({
      'POST /api/specialists': (init) => {
        expect(JSON.parse(String(init?.body))).toEqual({ name: 'Novo', slug: 'novo', project_id: 1 })
        return jsonResponse(created, 201)
      },
      'PATCH /api/specialists/5': (init) => {
        expect(JSON.parse(String(init?.body))).toEqual({ enabled: false })
        return jsonResponse({ ...created, enabled: false })
      },
      'DELETE /api/specialists/5': () => new Response(null, { status: 204 }),
    }))
    const store = useSpecialistsStore()
    await store.create({ name: 'Novo', slug: 'novo', project_id: 1 })
    expect(store.byId(5)?.enabled).toBe(true)
    await store.update(5, { enabled: false })
    expect(store.byId(5)?.enabled).toBe(false)
    await store.remove(5)
    expect(store.byId(5)).toBeUndefined()
  })

  it('o erro de validação chega como está, em português', async () => {
    vi.stubGlobal('fetch', routeFetch({
      'PATCH /api/specialists/1': () => jsonResponse({ detail: 'O horário deve estar no formato HH:MM, de 00:00 a 23:59.' }, 422),
    }))
    const store = useSpecialistsStore()
    store.list = [makeSpecialist()]
    await expect(store.update(1, { schedules: [{ days: '1', time: '8' }] })).rejects.toThrow('O horário deve estar no formato HH:MM, de 00:00 a 23:59.')
  })

  it('"Rodar agora" manda o texto e guarda a execução como a última do agente', async () => {
    const run = makeSpecialistRun({ id: 7, session_id: 's9' })
    vi.stubGlobal('fetch', routeFetch({
      'POST /api/specialists/1/run': (init) => {
        expect(JSON.parse(String(init?.body))).toEqual({ text: 'Só os de hoje.' })
        return jsonResponse(run, 202)
      },
    }))
    const store = useSpecialistsStore()
    store.list = [makeSpecialist()]
    const result = await store.runNow(1, 'Só os de hoje.')
    expect(result.session_id).toBe('s9')
    expect(store.byId(1)?.last_run?.id).toBe(7)
  })

  it('aceita a execução que já nasceu falha, sem sessão', async () => {
    const run = makeSpecialistRun({ id: 8, session_id: null, outcome: 'failed', reason: 'A pasta do projeto não está disponível.' })
    vi.stubGlobal('fetch', routeFetch({ 'POST /api/specialists/1/run': () => jsonResponse(run, 202) }))
    const store = useSpecialistsStore()
    store.list = [makeSpecialist()]
    const result = await store.runNow(1)
    expect(result.session_id).toBeNull()
    expect(store.byId(1)?.last_run?.outcome).toBe('failed')
  })

  it('specialist.changed recarrega a lista', async () => {
    const fetch = routeFetch({ 'GET /api/specialists': () => jsonResponse([makeSpecialist({ name: 'Renomeado' })]) })
    vi.stubGlobal('fetch', fetch)
    const store = useSpecialistsStore()
    store.list = [makeSpecialist()]
    store.applyChanged({ id: 1 })
    await vi.waitFor(() => expect(store.byId(1)?.name).toBe('Renomeado'))
    expect(store.changes[1]).toBe(1)
  })

  it('specialist.run atualiza a última execução e a lista de execuções carregada', async () => {
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/specialists/1/runs?limit=50': () => jsonResponse([makeSpecialistRun({ id: 1 })]),
    }))
    const store = useSpecialistsStore()
    store.list = [makeSpecialist({ last_run: makeSpecialistRun({ id: 1 }) })]
    await store.loadRuns(1)
    store.applyRun(makeSpecialistRun({ id: 2, outcome: 'failed' }))
    expect(store.byId(1)?.last_run?.id).toBe(2)
    expect(store.runsOf(1).map((r) => r.id)).toEqual([2, 1])
    // a mudança de desfecho da mesma execução troca o registro, não duplica
    store.applyRun(makeSpecialistRun({ id: 2, outcome: 'concluded' }))
    expect(store.runsOf(1).map((r) => r.outcome)).toEqual(['concluded', 'running'])
    expect(store.byId(1)?.last_run?.outcome).toBe('concluded')
  })

  it('uma execução mais antiga não derruba a última', () => {
    const store = useSpecialistsStore()
    store.list = [makeSpecialist({ last_run: makeSpecialistRun({ id: 5 }) })]
    store.applyRun(makeSpecialistRun({ id: 3 }))
    expect(store.byId(1)?.last_run?.id).toBe(5)
  })

  it('specialist.notice com um aviso novo entra no começo e conta como não lido', () => {
    const store = useSpecialistsStore()
    store.notices = [makeSpecialistNotice({ id: 1, read_at: 1_790_000_100 })]
    store.applyNotice(makeSpecialistNotice({ id: 2 }))
    expect(store.notices.map((n) => n.id)).toEqual([2, 1])
    expect(store.unreadCount).toBe(1)
    // o mesmo aviso de novo não duplica
    store.applyNotice(makeSpecialistNotice({ id: 2 }))
    expect(store.notices).toHaveLength(2)
  })

  it('specialist.notice com read_ids marca como lidos', () => {
    const store = useSpecialistsStore()
    store.notices = [makeSpecialistNotice({ id: 1 }), makeSpecialistNotice({ id: 2 }), makeSpecialistNotice({ id: 3 })]
    store.applyNotice({ read_ids: [1, 3] })
    expect(store.notices.map((n) => n.read_at !== null)).toEqual([true, false, true])
    expect(store.unreadCount).toBe(1)
  })

  it('ignora um evento de aviso que não é nem uma forma nem a outra', () => {
    const store = useSpecialistsStore()
    store.applyNotice(null)
    store.applyNotice({ foo: 1 })
    store.applyNotice({ read_ids: 'x' })
    expect(store.notices).toEqual([])
  })

  it('carrega os avisos e marca como lidos pela API', async () => {
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/specialist-notices': () => jsonResponse([makeSpecialistNotice({ id: 1 }), makeSpecialistNotice({ id: 2 })]),
      'POST /api/specialist-notices/read': (init) => {
        expect(JSON.parse(String(init?.body))).toEqual({ ids: [1] })
        return jsonResponse({ updated: 1 })
      },
    }))
    const store = useSpecialistsStore()
    await store.loadNotices()
    expect(store.unreadCount).toBe(2)
    await store.markRead([1])
    expect(store.unreadCount).toBe(1)
  })
})

class FakeSocket implements SocketLike {
  onopen: ((ev: never) => void) | null = null
  onclose: ((ev: never) => void) | null = null
  onerror: ((ev: never) => void) | null = null
  onmessage: ((ev: { data: unknown }) => void) | null = null
  close() {}
}

describe('specialists store: eventos do WebSocket', () => {
  it('reage a specialist.changed, specialist.run e specialist.notice', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/specialists': () => jsonResponse([makeSpecialist({ name: 'Do servidor' })]) }))
    const fake = new FakeSocket()
    const socket = new EventSocket({ url: 'ws://x', createSocket: () => fake })
    const off = bindRealtime(socket)
    socket.connect()
    fake.onopen?.(undefined as never)
    const store = useSpecialistsStore()
    store.list = [makeSpecialist()]
    const send = (type: string, data: unknown) => fake.onmessage?.({ data: JSON.stringify({ session_id: null, seq: 0, type, data }) })

    send('specialist.run', makeSpecialistRun({ id: 4, outcome: 'waiting' }))
    expect(store.byId(1)?.last_run?.outcome).toBe('waiting')
    send('specialist.notice', makeSpecialistNotice({ id: 9 }))
    expect(store.unreadCount).toBe(1)
    send('specialist.notice', { read_ids: [9] })
    expect(store.unreadCount).toBe(0)
    send('specialist.changed', { id: 1 })
    await vi.waitFor(() => expect(store.byId(1)?.name).toBe('Do servidor'))
    off()
    socket.close()
  })
})
