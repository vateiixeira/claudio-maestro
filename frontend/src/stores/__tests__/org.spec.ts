import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick } from 'vue'
import { useOrgStore } from '../org'
import { useSessionsStore } from '../sessions'
import {
  jsonResponse, makeAgent, makeDecision, makeNotice, makeRoutine, makeRun, makeSession, routeFetch,
} from '../../test/factories'

beforeEach(() => setActivePinia(createPinia()))
afterEach(() => vi.unstubAllGlobals())

describe('org store: árvore', () => {
  function seeded() {
    const store = useOrgStore()
    store.agents = [
      makeAgent({ id: 1, slug: 'cto', name: 'CTO', reports_to: null }),
      makeAgent({ id: 2, slug: 'zeta', name: 'Zeta', reports_to: 1 }),
      makeAgent({ id: 3, slug: 'alfa', name: 'Alfa', reports_to: 1 }),
      makeAgent({ id: 4, slug: 'sub', name: 'Sub', reports_to: 3 }),
      makeAgent({ id: 5, slug: 'ana', name: 'Ana', reports_to: null }),
      makeAgent({ id: 6, slug: 'outro', name: 'Outro', project_id: 2 }),
    ]
    return store
  }

  it('tree agrupa por chefe e ordena por nome', () => {
    const store = seeded()
    const tree = store.tree(1)
    expect(tree.map((n) => n.agent.name)).toEqual(['Ana', 'CTO'])
    const cto = tree[1]!
    expect(cto.children.map((n) => n.agent.name)).toEqual(['Alfa', 'Zeta'])
    expect(cto.children[0]!.children.map((n) => n.agent.name)).toEqual(['Sub'])
    expect(cto.children[1]!.children).toEqual([])
    // outro projeto não entra
    expect(store.tree(2).map((n) => n.agent.name)).toEqual(['Outro'])
    expect(store.tree(99)).toEqual([])
  })

  it('topOf devolve o agente sem chefe (o primeiro por nome)', () => {
    const store = seeded()
    expect(store.topOf(1)?.name).toBe('Ana')
    expect(store.topOf(2)?.name).toBe('Outro')
    expect(store.topOf(99)).toBeUndefined()
  })

  it('byId e byProject', () => {
    const store = seeded()
    expect(store.byId(3)?.slug).toBe('alfa')
    expect(store.byId(99)).toBeUndefined()
    expect(store.byProject(1).map((a) => a.name)).toEqual(['Alfa', 'Ana', 'CTO', 'Sub', 'Zeta'])
  })

  it('isMainSession acha o agente dono da conversa principal', () => {
    const store = useOrgStore()
    store.agents = [makeAgent({ id: 1, main_session_id: 'conv-1' }), makeAgent({ id: 2, slug: 'b', main_session_id: null })]
    expect(store.isMainSession('conv-1')?.id).toBe(1)
    expect(store.isMainSession('outra')).toBeUndefined()
  })
})

describe('org store: mudança local de agente', () => {
  it('upsertAgent troca o agente existente no mesmo lugar e acrescenta o novo', () => {
    const store = useOrgStore()
    store.agents = [makeAgent({ id: 1, name: 'Um' }), makeAgent({ id: 2, slug: 'b', name: 'Dois' })]
    store.upsertAgent(makeAgent({ id: 1, name: 'Um renomeado' }))
    expect(store.agents.map((a) => a.name)).toEqual(['Um renomeado', 'Dois'])
    store.upsertAgent(makeAgent({ id: 3, slug: 'c', name: 'Três' }))
    expect(store.agents.map((a) => a.id)).toEqual([1, 2, 3])
  })

  it('removeAgent tira o agente e as execuções guardadas dele', () => {
    const store = useOrgStore()
    store.agents = [makeAgent({ id: 1 }), makeAgent({ id: 2, slug: 'b' })]
    store.runs = { 1: [makeRun({ id: 9, agent_id: 1 })], 2: [makeRun({ id: 10, agent_id: 2 })] }
    store.removeAgent(1)
    expect(store.agents.map((a) => a.id)).toEqual([2])
    expect(store.runsOf(1)).toEqual([])
    expect(store.runsOf(2)).toHaveLength(1)
  })
})

describe('org store: carga', () => {
  it('carrega a lista e guarda a mensagem quando falha', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/agents': () => jsonResponse([makeAgent(), makeAgent({ id: 2, slug: 'b', name: 'B' })]) }))
    const store = useOrgStore()
    await store.load()
    expect(store.agents.map((a) => a.name)).toEqual(['CTO', 'B'])
    expect(store.loaded).toBe(true)
    expect(store.error).toBeNull()

    vi.stubGlobal('fetch', routeFetch({ 'GET /api/agents': () => jsonResponse({ detail: 'Quebrou.' }, 500) }))
    await store.load()
    expect(store.error).toBe('Quebrou.')
    expect(store.agents).toHaveLength(2)
  })

  it('loadRoutines e routinesOf guardam por projeto', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/routines?project_id=1': () => jsonResponse([makeRoutine()]) }))
    const store = useOrgStore()
    expect(store.routinesOf(1)).toEqual([])
    await store.loadRoutines(1)
    expect(store.routinesOf(1).map((r) => r.name)).toEqual(['Triagem da manhã'])
    expect(store.routinesOf(2)).toEqual([])
  })

  it('loadDecisions guarda só as pendentes', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/decisions?pending=true': () => jsonResponse([makeDecision({ id: 3 })]) }))
    const store = useOrgStore()
    await store.loadDecisions()
    expect(store.decisionsPending.map((d) => d.id)).toEqual([3])
  })
})

describe('org store: eventos', () => {
  it('agent.changed recarrega só aquele agente', async () => {
    const fetch = routeFetch({ 'GET /api/agents/1': () => jsonResponse(makeAgent({ name: 'Renomeado', unseen: 2 })) })
    vi.stubGlobal('fetch', fetch)
    const store = useOrgStore()
    store.agents = [makeAgent(), makeAgent({ id: 2, slug: 'b', name: 'B' })]
    store.applyEvent('agent.changed', { id: 1 })
    await vi.waitFor(() => expect(store.byId(1)?.name).toBe('Renomeado'))
    expect(store.byId(1)?.unseen).toBe(2)
    expect(store.byId(2)?.name).toBe('B')
    expect(store.changes[1]).toBe(1)
    expect(fetch).toHaveBeenCalledTimes(1)
  })

  it('agent.changed de um agente novo o acrescenta e de um removido o tira', async () => {
    let gone = false
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/agents/7': () => (gone ? jsonResponse({ detail: 'Agente não encontrado.' }, 404) : jsonResponse(makeAgent({ id: 7, slug: 'novo', name: 'Novo' }))),
    }))
    const store = useOrgStore()
    store.applyEvent('agent.changed', { id: 7 })
    await vi.waitFor(() => expect(store.byId(7)?.name).toBe('Novo'))
    gone = true
    store.runs = { 7: [makeRun({ agent_id: 7 })] }
    store.applyEvent('agent.changed', { id: 7 })
    await vi.waitFor(() => expect(store.byId(7)).toBeUndefined())
    expect(store.runsOf(7)).toEqual([])
  })

  it('agent.changed com falha de rede mantém o agente como estava', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/agents/1': () => jsonResponse({ detail: 'x' }, 500) }))
    const store = useOrgStore()
    store.agents = [makeAgent()]
    store.applyEvent('agent.changed', { id: 1 })
    await vi.waitFor(() => expect(store.changes[1]).toBe(1))
    await new Promise((r) => setTimeout(r, 0))
    expect(store.byId(1)?.name).toBe('CTO')
  })

  it('ignora agent.changed sem id', () => {
    const fetch = vi.fn()
    vi.stubGlobal('fetch', fetch)
    const store = useOrgStore()
    store.applyEvent('agent.changed', null)
    store.applyEvent('agent.changed', { id: 'x' })
    expect(fetch).not.toHaveBeenCalled()
  })

  it('agent.announcement relê o agente (o unseen é recontado pelo servidor)', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/agents/1': () => jsonResponse(makeAgent({ unseen: 3 })) }))
    const store = useOrgStore()
    store.agents = [makeAgent({ unseen: 2 })]
    store.applyEvent('agent.announcement', { id: 9, agent_id: 1, run_id: 4, session_id: 's', text: 'ok', created_at: 1, delivered_at: null })
    await vi.waitFor(() => expect(store.byId(1)?.unseen).toBe(3))
    expect(store.changes[1]).toBe(1)
  })

  it('agent.run atualiza a lista de execuções e a última do agente', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/agents/1/runs?limit=50': () => jsonResponse([makeRun({ id: 1 })]) }))
    const store = useOrgStore()
    store.agents = [makeAgent({ last_run: makeRun({ id: 1 }) })]
    await store.loadRuns(1)
    store.applyEvent('agent.run', makeRun({ id: 2, outcome: 'failed', started_at: 1_790_000_100 }))
    expect(store.byId(1)?.last_run?.id).toBe(2)
    expect(store.runsOf(1).map((r) => r.id)).toEqual([2, 1])
    // a mudança de resultado da mesma execução troca o registro, não duplica
    store.applyEvent('agent.run', makeRun({ id: 2, outcome: 'concluded', started_at: 1_790_000_100 }))
    expect(store.runsOf(1).map((r) => r.outcome)).toEqual(['concluded', 'running'])
    expect(store.byId(1)?.last_run?.outcome).toBe('concluded')
  })

  it('uma execução mais antiga não derruba a última', () => {
    const store = useOrgStore()
    store.agents = [makeAgent({ last_run: makeRun({ id: 5, started_at: 50 }) })]
    store.applyEvent('agent.run', makeRun({ id: 3, started_at: 30 }))
    expect(store.byId(1)?.last_run?.id).toBe(5)
  })

  it('agent.run sem a lista carregada só atualiza a última; evento malformado é ignorado', () => {
    const store = useOrgStore()
    store.agents = [makeAgent()]
    store.applyEvent('agent.run', makeRun({ id: 4, outcome: 'waiting' }))
    expect(store.byId(1)?.last_run?.outcome).toBe('waiting')
    expect(store.runsOf(1)).toEqual([])
    store.applyEvent('agent.run', { foo: 1 })
    store.applyEvent('agent.run', null)
    expect(store.byId(1)?.last_run?.id).toBe(4)
  })

  it('mantém as execuções em curso ao limitar o histórico', () => {
    const store = useOrgStore()
    store.agents = [makeAgent()]
    const running = makeRun({ id: 1, started_at: 1, outcome: 'running' })
    const waiting = makeRun({ id: 2, started_at: 2, outcome: 'waiting' })
    store.runs = { 1: [waiting, running] }
    for (let id = 3; id <= 60; id++) store.applyEvent('agent.run', makeRun({ id, started_at: 100 + id, outcome: 'concluded' }))
    expect(store.runsOf(1)).toHaveLength(52)
    expect(store.runsOf(1)).toContainEqual(running)
    expect(store.runsOf(1)).toContainEqual(waiting)
    expect(store.runsOf(1).filter((r) => r.outcome === 'concluded')).toHaveLength(50)
  })

  it('decision mantém a lista de pendentes: entra a pendente, sai a respondida', () => {
    const store = useOrgStore()
    store.applyEvent('decision', makeDecision({ id: 1 }))
    store.applyEvent('decision', makeDecision({ id: 2 }))
    store.applyEvent('decision', makeDecision({ id: 1, question: 'Editada?' }))
    expect(store.decisionsPending.map((d) => d.id)).toEqual([2, 1])
    expect(store.decisionsPending.find((d) => d.id === 1)?.question).toBe('Editada?')
    store.applyEvent('decision', makeDecision({ id: 1, status: 'answered', answer: 'Sim' }))
    expect(store.decisionsPending.map((d) => d.id)).toEqual([2])
    store.applyEvent('decision', makeDecision({ id: 2, status: 'expired' }))
    expect(store.decisionsPending).toEqual([])
    store.applyEvent('decision', { foo: 1 })
    expect(store.decisionsPending).toEqual([])
  })
})

describe('org store: execuções lidas durante eventos', () => {
  it('preserva eventos recebidos durante a leitura inicial das execuções', async () => {
    let resolve!: (response: Response) => void
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/agents/1/runs?limit=50': () => new Promise<Response>((r) => { resolve = r }) }))
    const store = useOrgStore()
    const loading = store.loadRuns(1)
    store.applyEvent('agent.run', makeRun({ id: 9, outcome: 'cancelled' }))
    resolve(jsonResponse([makeRun({ id: 9, outcome: 'starting' })]))
    await loading
    expect(store.runsOf(1)[0]?.outcome).toBe('cancelled')
  })

  it('leituras concorrentes de agentes diferentes preservam ambos os históricos', async () => {
    const resolvers: Record<number, (response: Response) => void> = {}
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/agents/1/runs?limit=50': () => new Promise<Response>((r) => { resolvers[1] = r }),
      'GET /api/agents/2/runs?limit=50': () => new Promise<Response>((r) => { resolvers[2] = r }),
    }))
    const store = useOrgStore()
    const first = store.loadRuns(1)
    const second = store.loadRuns(2)
    resolvers[2]!(jsonResponse([makeRun({ id: 20, agent_id: 2 })]))
    resolvers[1]!(jsonResponse([makeRun({ id: 10, agent_id: 1 })]))
    await Promise.all([first, second])
    expect(store.runsOf(1).map((r) => r.id)).toEqual([10])
    expect(store.runsOf(2).map((r) => r.id)).toEqual([20])
  })
})

describe('org store: avisos', () => {
  it('unreadCount conta só não lidas', () => {
    const store = useOrgStore()
    store.notices = [makeNotice({ id: 1, read_at: 5 }), makeNotice({ id: 2 }), makeNotice({ id: 3 })]
    expect(store.unreadCount).toBe(2)
  })

  it('agent.notice com um aviso novo entra no começo e o mesmo não duplica', () => {
    const store = useOrgStore()
    store.notices = [makeNotice({ id: 1, read_at: 5 })]
    store.applyEvent('agent.notice', makeNotice({ id: 2 }))
    expect(store.notices.map((n) => n.id)).toEqual([2, 1])
    store.applyEvent('agent.notice', makeNotice({ id: 2 }))
    expect(store.notices).toHaveLength(2)
  })

  it('agent.notice com read_ids marca como lidos; formas inválidas são ignoradas', () => {
    const store = useOrgStore()
    store.notices = [makeNotice({ id: 1 }), makeNotice({ id: 2 }), makeNotice({ id: 3 })]
    store.applyEvent('agent.notice', { read_ids: [1, 3] })
    expect(store.notices.map((n) => n.read_at !== null)).toEqual([true, false, true])
    store.applyEvent('agent.notice', null)
    store.applyEvent('agent.notice', { foo: 1 })
    store.applyEvent('agent.notice', { read_ids: 'x' })
    expect(store.notices).toHaveLength(3)
  })

  it('avisa os ouvintes só de um aviso novo', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/agent-notices': () => jsonResponse([makeNotice({ id: 1 })]) }))
    const store = useOrgStore()
    const heard: number[] = []
    const off = store.onNewNotice((n) => heard.push(n.id))
    await store.loadNotices()
    store.applyEvent('agent.notice', { read_ids: [1] })
    store.applyEvent('agent.notice', makeNotice({ id: 2 }))
    store.applyEvent('agent.notice', makeNotice({ id: 2 }))
    expect(heard).toEqual([2])
    off()
    store.applyEvent('agent.notice', makeNotice({ id: 3 }))
    expect(heard).toEqual([2])
  })

  it('markRead chama a API e marca localmente', async () => {
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/agent-notices': () => jsonResponse([makeNotice({ id: 1 }), makeNotice({ id: 2 })]),
      'POST /api/agent-notices/read': (init) => {
        expect(JSON.parse(String(init?.body))).toEqual({ ids: [1] })
        return jsonResponse({ updated: 1 })
      },
    }))
    const store = useOrgStore()
    await store.loadNotices()
    expect(store.unreadCount).toBe(2)
    await store.markRead([1])
    expect(store.unreadCount).toBe(1)
    await store.markRead([])
  })

  it('loadNotices guarda o erro', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/agent-notices': () => jsonResponse({ detail: 'Falhou.' }, 500) }))
    const store = useOrgStore()
    await store.loadNotices()
    expect(store.noticesError).toBe('Falhou.')
    expect(store.noticesLoaded).toBe(true)
  })
})

describe('org store: conversa principal', () => {
  it('openMain cria a conversa, guarda o id e navega para ela', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'POST /api/agents/1/main': () => jsonResponse({ session_id: 'conv-1' }) }))
    const store = useOrgStore()
    store.agents = [makeAgent()]
    const router = { push: vi.fn(async () => undefined) }
    await store.openMain(1, router)
    expect(store.byId(1)?.main_session_id).toBe('conv-1')
    expect(router.push).toHaveBeenCalledWith({ name: 'session', params: { id: 'conv-1' } })
  })

  it('openMain deixa o erro subir e não navega', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'POST /api/agents/1/main': () => jsonResponse({ detail: 'Sem pasta.' }, 409) }))
    const store = useOrgStore()
    store.agents = [makeAgent()]
    const router = { push: vi.fn(async () => undefined) }
    await expect(store.openMain(1, router)).rejects.toThrow('Sem pasta.')
    expect(router.push).not.toHaveBeenCalled()
  })
})

describe('org store: espera da conversa principal', () => {
  it('relê a lista quando a principal passa a pedir ok e quando deixa de pedir', async () => {
    let unseen = 0
    const fetch = routeFetch({ 'GET /api/agents': () => jsonResponse([makeAgent({ unseen, main_session_id: 'main' })]) })
    vi.stubGlobal('fetch', fetch)
    const store = useOrgStore()
    const sessions = useSessionsStore()
    store.agents = [makeAgent({ unseen: 0, main_session_id: 'main' })]
    sessions.setForProject(1, [makeSession({ session_id: 'main', agent_id: 1 })])
    await nextTick()
    expect(fetch).not.toHaveBeenCalled()

    unseen = 1
    sessions.setForProject(1, [makeSession({ session_id: 'main', agent_id: 1, pending_kind: 'tool' })])
    await vi.waitFor(() => expect(store.byId(1)?.unseen).toBe(1))
    expect(fetch).toHaveBeenCalledTimes(1)

    unseen = 0
    sessions.setForProject(1, [makeSession({ session_id: 'main', agent_id: 1, pending_kind: null })])
    await vi.waitFor(() => expect(store.byId(1)?.unseen).toBe(0))
    expect(fetch).toHaveBeenCalledTimes(2)
  })

  it('a espera de uma execução (não a principal) não dispara nada', async () => {
    const fetch = routeFetch({ 'GET /api/agents': () => jsonResponse([makeAgent({ main_session_id: 'main' })]) })
    vi.stubGlobal('fetch', fetch)
    const store = useOrgStore()
    const sessions = useSessionsStore()
    store.agents = [makeAgent({ main_session_id: 'main' })]
    sessions.setForProject(1, [makeSession({ session_id: 'run', agent_id: 1, pending_kind: 'tool' })])
    await nextTick()
    expect(fetch).not.toHaveBeenCalled()
  })
})

describe('org store: reloadOpen', () => {
  it('relê só as execuções e rotinas que já foram abertas', async () => {
    const fetch = routeFetch({
      'GET /api/agents/1/runs?limit=50': () => jsonResponse([makeRun()]),
      'GET /api/routines?project_id=1': () => jsonResponse([makeRoutine()]),
    })
    vi.stubGlobal('fetch', fetch)
    const store = useOrgStore()
    await store.loadRuns(1)
    await store.loadRoutines(1)
    fetch.mockClear()
    await store.reloadOpen()
    expect(fetch.mock.calls.map(([u]) => u).sort()).toEqual(['/api/agents/1/runs?limit=50', '/api/routines?project_id=1'])
  })
})
