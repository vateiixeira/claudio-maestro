import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useSpecialistsStore } from '../specialists'
import { useSessionsStore } from '../sessions'
import { nextTick } from 'vue'
import { jsonResponse, makeSession, makeSpecialist, makeSpecialistNotice, makeSpecialistRun, routeFetch } from '../../test/factories'

beforeEach(() => setActivePinia(createPinia()))
afterEach(() => vi.unstubAllGlobals())

describe('specialists store', () => {
  it('guarda o cancelamento de uma execução na fila', async () => {
    const queued = makeSpecialistRun({ id: 9, outcome: 'queued', session_id: null })
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/specialists/1/runs?limit=50': () => jsonResponse([queued]),
      'POST /api/specialists/1/runs/9/cancel': () => jsonResponse({ ...queued, outcome: 'cancelled' }),
    }))
    const store = useSpecialistsStore()
    store.list = [makeSpecialist({ last_run: queued })]
    await store.loadRuns(1)
    await store.cancelRun(1, 9)
    expect(store.runsOf(1)[0]?.outcome).toBe('cancelled')
    expect(store.byId(1)?.last_run?.outcome).toBe('cancelled')
  })

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

  it('reordena pela hora de início quando uma pendência antiga começa', () => {
    const store = useSpecialistsStore()
    const queued = makeSpecialistRun({ id: 2, started_at: 10, outcome: 'queued', session_id: null })
    const requestedLater = makeSpecialistRun({ id: 3, started_at: 20, outcome: 'queued', session_id: null })
    store.list = [makeSpecialist({ last_run: requestedLater })]
    store.runs = { 1: [requestedLater, queued] }

    const starting = { ...queued, started_at: 30, outcome: 'starting' as const, session_id: 's2' }
    store.applyRun(starting)

    expect(store.byId(1)?.last_run).toEqual(starting)
    expect(store.runsOf(1).map((run) => run.id)).toEqual([2, 3])
  })

  it('um id maior com início mais antigo não substitui a última execução', () => {
    const store = useSpecialistsStore()
    const latest = makeSpecialistRun({ id: 2, started_at: 30 })
    store.list = [makeSpecialist({ last_run: latest })]
    store.runs = { 1: [latest] }

    store.applyRun(makeSpecialistRun({ id: 3, started_at: 20, outcome: 'queued', session_id: null }))

    expect(store.byId(1)?.last_run).toEqual(latest)
    expect(store.runsOf(1).map((run) => run.id)).toEqual([2, 3])
  })

  it('ordena antes de limitar o histórico quando uma execução antiga muda a hora de início', () => {
    const store = useSpecialistsStore()
    const queued = makeSpecialistRun({ id: 1, started_at: 1, outcome: 'queued', session_id: null })
    const history = Array.from({ length: 50 }, (_, index) => makeSpecialistRun({ id: 51 - index, started_at: 51 - index, outcome: 'concluded' }))
    store.list = [makeSpecialist({ last_run: history[0]! })]
    store.runs = { 1: [...history, queued] }

    store.applyRun({ ...queued, started_at: 100, outcome: 'concluded', session_id: 's1' })

    expect(store.runsOf(1)).toHaveLength(50)
    expect(store.runsOf(1)[0]?.id).toBe(1)
    expect(store.runsOf(1).some((run) => run.id === 2)).toBe(false)
  })

  it('mantém todas as pendências ao limitar o histórico atualizado por eventos', () => {
    const store = useSpecialistsStore()
    store.list = [makeSpecialist()]
    const queued = makeSpecialistRun({ id: 1, outcome: 'queued', session_id: null })
    const starting = makeSpecialistRun({ id: 2, outcome: 'starting', session_id: 's2' })
    store.runs = { 1: [starting, queued] }

    for (let id = 3; id <= 56; id++) store.applyRun(makeSpecialistRun({ id, outcome: 'concluded' }))

    expect(store.runsOf(1)).toHaveLength(52)
    expect(store.runsOf(1).filter((run) => run.outcome === 'concluded')).toHaveLength(50)
    expect(store.runsOf(1)).toContainEqual(queued)
    expect(store.runsOf(1)).toContainEqual(starting)

    store.applyRun({ ...queued, outcome: 'cancelled' })
    expect(store.runsOf(1)).toHaveLength(51)
    expect(store.runsOf(1)).toContainEqual(starting)
    expect(store.runsOf(1).filter((run) => run.outcome !== 'starting')).toHaveLength(50)
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

  it('avisa os ouvintes só de um aviso novo, nunca de read_ids, de repetido ou do que veio da lista', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/specialist-notices': () => jsonResponse([makeSpecialistNotice({ id: 1 })]) }))
    const store = useSpecialistsStore()
    const heard: number[] = []
    const off = store.onNewNotice((n) => heard.push(n.id))
    await store.loadNotices()
    store.applyNotice({ read_ids: [1] })
    store.applyNotice(makeSpecialistNotice({ id: 2 }))
    store.applyNotice(makeSpecialistNotice({ id: 2 }))
    store.applyNotice({ foo: 1 })
    expect(heard).toEqual([2])
    off()
    store.applyNotice(makeSpecialistNotice({ id: 3 }))
    expect(heard).toEqual([2])
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

describe('specialists store: conversa principal', () => {
  it('openMain cria a conversa, guarda o id e navega para ela', async () => {
    const fetch = routeFetch({ 'POST /api/agents/1/main': () => jsonResponse({ session_id: 'conv-1' }) })
    vi.stubGlobal('fetch', fetch)
    const store = useSpecialistsStore()
    store.list = [makeSpecialist()]
    const router = { push: vi.fn(async () => undefined) }
    await store.openMain(1, router)
    expect(store.byId(1)?.main_session_id).toBe('conv-1')
    expect(router.push).toHaveBeenCalledWith({ name: 'session', params: { id: 'conv-1' } })
  })

  it('openMain resolve de novo uma conversa apagada mesmo com id em cache', async () => {
    const fetch = routeFetch({ 'POST /api/agents/1/main': () => jsonResponse({ session_id: 'conv-2' }) })
    vi.stubGlobal('fetch', fetch)
    const store = useSpecialistsStore()
    store.list = [makeSpecialist({ main_session_id: 'conv-1' })]
    const router = { push: vi.fn(async () => undefined) }
    await store.openMain(1, router)
    expect(fetch).toHaveBeenCalled()
    expect(store.byId(1)?.main_session_id).toBe('conv-2')
    expect(router.push).toHaveBeenCalledWith({ name: 'session', params: { id: 'conv-2' } })
  })

  it('openMain deixa o erro subir e não navega', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'POST /api/agents/1/main': () => jsonResponse({ detail: 'Sem pasta.' }, 409) }))
    const store = useSpecialistsStore()
    store.list = [makeSpecialist()]
    const router = { push: vi.fn(async () => undefined) }
    await expect(store.openMain(1, router)).rejects.toThrow('Sem pasta.')
    expect(router.push).not.toHaveBeenCalled()
  })

  it('isMainSession acha o agente dono da conversa principal', () => {
    const store = useSpecialistsStore()
    store.list = [makeSpecialist({ id: 1, main_session_id: 'conv-1' }), makeSpecialist({ id: 2, slug: 'b', main_session_id: null })]
    expect(store.isMainSession('conv-1')?.id).toBe(1)
    expect(store.isMainSession('outra')).toBeUndefined()
  })

  it('specialist.announcement relê a lista e atualiza o contador unseen', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/specialists': () => jsonResponse([makeSpecialist({ unseen: 3 })]) }))
    const store = useSpecialistsStore()
    store.list = [makeSpecialist({ unseen: 2 })]
    store.applyAnnouncement({ id: 9, specialist_id: 1, run_id: 4, session_id: 's', text: 'ok', created_at: 1, delivered_at: null })
    await vi.waitFor(() => expect(store.byId(1)?.unseen).toBe(3))
  })

  it('specialist.changed também atualiza o unseen', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/specialists': () => jsonResponse([makeSpecialist({ unseen: 0, main_session_id: 'conv-1' })]) }))
    const store = useSpecialistsStore()
    store.list = [makeSpecialist({ unseen: 2 })]
    store.applyChanged({ id: 1 })
    await vi.waitFor(() => expect(store.byId(1)?.unseen).toBe(0))
  })
})

describe('specialists store: espera da conversa principal', () => {
  it('relê a lista quando a principal passa a pedir ok e quando deixa de pedir, e o contador acompanha', async () => {
    let unseen = 0
    const fetch = routeFetch({ 'GET /api/specialists': () => jsonResponse([makeSpecialist({ unseen, main_session_id: 'main' })]) })
    vi.stubGlobal('fetch', fetch)
    const store = useSpecialistsStore()
    const sessions = useSessionsStore()
    store.list = [makeSpecialist({ unseen: 0, main_session_id: 'main' })]
    sessions.setForProject(1, [makeSession({ session_id: 'main', agent_id: 1 })])
    await nextTick()
    expect(fetch).not.toHaveBeenCalled()

    // pede ok: o backend passa a contar +1, sem publicar nada
    unseen = 1
    sessions.setForProject(1, [makeSession({ session_id: 'main', agent_id: 1, pending_kind: 'tool' })])
    await vi.waitFor(() => expect(store.byId(1)?.unseen).toBe(1))
    expect(fetch).toHaveBeenCalledTimes(1)

    // a espera termina: o contador cai
    unseen = 0
    sessions.setForProject(1, [makeSession({ session_id: 'main', agent_id: 1, pending_kind: null })])
    await vi.waitFor(() => expect(store.byId(1)?.unseen).toBe(0))
    expect(fetch).toHaveBeenCalledTimes(2)
  })

  it('o estado awaiting_decision também conta, e a espera de uma execução não dispara nada', async () => {
    const fetch = routeFetch({ 'GET /api/specialists': () => jsonResponse([makeSpecialist({ main_session_id: 'main' })]) })
    vi.stubGlobal('fetch', fetch)
    const store = useSpecialistsStore()
    const sessions = useSessionsStore()
    store.list = [makeSpecialist({ main_session_id: 'main' })]
    sessions.setForProject(1, [makeSession({ session_id: 'run', agent_id: 1, pending_kind: 'tool' })])
    await nextTick()
    expect(fetch).not.toHaveBeenCalled()
    sessions.setForProject(1, [makeSession({ session_id: 'main', agent_id: 1, state: 'awaiting_decision' })])
    await vi.waitFor(() => expect(fetch).toHaveBeenCalledTimes(1))
  })
})

describe('api de anúncios e do GitHub', () => {
  it('listAnnouncements, getGithubSettings e putGithubSettings usam as rotas do backend', async () => {
    const fetch = routeFetch({
      'GET /api/agents/1/announcements?pending=true': () => jsonResponse([{ id: 1, run_id: 2, session_id: 's', text: 'x', created_at: 1, delivered_at: null }]),
      'GET /api/agents/1/announcements': () => jsonResponse([]),
      'GET /api/agents-github': () => jsonResponse({ login: 'vi', secret_set: true, hooks_port: 6670, queued: 0 }),
      'PUT /api/agents-github': (init) => {
        expect(JSON.parse(String(init?.body))).toEqual({ login: 'novo' })
        return jsonResponse({ login: 'novo', secret_set: true, hooks_port: 6670, queued: 0 })
      },
    })
    vi.stubGlobal('fetch', fetch)
    const api = await import('../../api/http')
    expect(await api.listAnnouncements(1, true)).toHaveLength(1)
    expect(await api.listAnnouncements(1, false)).toEqual([])
    expect((await api.getGithubSettings()).login).toBe('vi')
    expect((await api.putGithubSettings({ login: 'novo' })).login).toBe('novo')
  })
})

it('preserva eventos recebidos durante a leitura inicial das execuções', async () => {
  let resolve!: (response: Response) => void
  vi.stubGlobal('fetch', routeFetch({
    'GET /api/specialists/1/runs?limit=50': () => new Promise<Response>((r) => { resolve = r }),
  }))
  const store = useSpecialistsStore()
  const loading = store.loadRuns(1)
  const cancelled = makeSpecialistRun({ id: 9, outcome: 'cancelled' })
  store.applyRun(cancelled)
  resolve(jsonResponse([{ ...cancelled, outcome: 'queued' }]))
  await loading
  expect(store.runsOf(1)[0]?.outcome).toBe('cancelled')
})

it('leituras concorrentes de agentes diferentes preservam ambos os históricos', async () => {
  const resolvers: Record<number, (response: Response) => void> = {}
  vi.stubGlobal('fetch', routeFetch(Object.fromEntries([1, 2].map((id) => [
    `GET /api/specialists/${id}/runs?limit=50`, () => new Promise<Response>((r) => { resolvers[id] = r }),
  ]))))
  const store = useSpecialistsStore()
  const first = store.loadRuns(1)
  const second = store.loadRuns(2)
  resolvers[2]!(jsonResponse([makeSpecialistRun({ id: 2, specialist_id: 2 })]))
  await second
  resolvers[1]!(jsonResponse([makeSpecialistRun({ id: 1 })]))
  await first
  expect(store.runsOf(1)).toHaveLength(1)
  expect(store.runsOf(2)).toHaveLength(1)
})

it('a resposta atrasada de uma leitura anterior não substitui o histórico novo', async () => {
  const resolvers: ((response: Response) => void)[] = []
  vi.stubGlobal('fetch', routeFetch({
    'GET /api/specialists/1/runs?limit=50': () => new Promise<Response>((r) => { resolvers.push(r) }),
  }))
  const store = useSpecialistsStore()
  const first = store.loadRuns(1)
  const second = store.loadRuns(1)
  resolvers[1]!(jsonResponse([makeSpecialistRun({ id: 9, outcome: 'concluded' })]))
  await second
  resolvers[0]!(jsonResponse([makeSpecialistRun({ id: 9, outcome: 'running' })]))
  await first
  expect(store.runsOf(1)[0]?.outcome).toBe('concluded')
})

it('preserva pedidos antigos na fila além das cinquenta execuções recentes', async () => {
  const queued = makeSpecialistRun({ id: 1, started_at: 1, outcome: 'queued', session_id: null })
  const history = Array.from({ length: 50 }, (_, i) => makeSpecialistRun({ id: i + 2, started_at: 100 + i, outcome: 'concluded' }))
  vi.stubGlobal('fetch', routeFetch({
    'GET /api/specialists/1/runs?limit=50': () => jsonResponse([...history, queued]),
  }))
  const store = useSpecialistsStore()
  await store.loadRuns(1)
  expect(store.runsOf(1)).toHaveLength(51)
  expect(store.runsOf(1).find((run) => run.id === 1)?.outcome).toBe('queued')
})
