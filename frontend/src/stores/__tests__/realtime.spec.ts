import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { EventSocket, type SocketLike } from '../../api/socket'
import { bindRealtime, loadEverything } from '../realtime'
import { useSessionsStore } from '../sessions'
import { useProjectsStore } from '../projects'
import { useGitStore } from '../git'
import { useModelsStore } from '../models'
import { useGroupsStore } from '../groups'
import { useLabelsStore } from '../labels'
import { useDigestStore } from '../digest'
import { useClosureStore } from '../closure'
import { useDeliveriesStore } from '../deliveries'
import { useClaudeCliStore } from '../claudeCli'
import { useOrgStore } from '../org'
import { useTasksStore } from '../tasks'
import { jsonResponse, makeAgent, makeDecision, makeGroup, makeLabel, makeNotice, makeProject, makeRun, makeSession, makeTask, makeTaskDetail } from '../../test/factories'

class FakeSocket implements SocketLike {
  onopen: ((ev: unknown) => void) | null = null
  onclose: ((ev: unknown) => void) | null = null
  onerror: ((ev: unknown) => void) | null = null
  onmessage: ((ev: { data: unknown }) => void) | null = null
  close() {}
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('bindRealtime', () => {
  it('leva session.digest e digest.status ao store do agente', () => {
    const sockets: FakeSocket[] = []
    const socket = new EventSocket({
      url: 'ws://x/ws',
      createSocket: () => {
        const s = new FakeSocket()
        sockets.push(s)
        return s
      },
      initialDelay: 10,
    })
    bindRealtime(socket)
    socket.connect()
    sockets[0]!.onopen?.({})
    const digest = { session_id: 's1', read_at: 1, short: 'Faz X', phases: [], plan_done: false, error: null, error_at: null }
    sockets[0]!.onmessage?.({
      data: JSON.stringify({ session_id: null, seq: 0, type: 'session.digest', data: { session_id: 's1', digest } }),
    })
    sockets[0]!.onmessage?.({
      data: JSON.stringify({ session_id: null, seq: 0, type: 'digest.status', data: { enabled: true, running: true, next_run_at: null, paused_until: null } }),
    })
    const store = useDigestStore()
    expect(store.digests.s1?.short).toBe('Faz X')
    expect(store.status?.running).toBe(true)
  })

  it('leva session.closure ao store da verificação e o invalida ao reconectar', () => {
    const sockets: FakeSocket[] = []
    const socket = new EventSocket({ url: 'ws://x/ws', createSocket: () => { const s = new FakeSocket(); sockets.push(s); return s }, initialDelay: 10 })
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse([])))
    bindRealtime(socket)
    socket.connect()
    sockets[0]!.onopen?.({})
    const closure = { session_id: 's1', verdict: 'can_close', user_actions: [], missing: [], evidence: null, checked_at: 5, error: null, error_at: null }
    sockets[0]!.onmessage?.({
      data: JSON.stringify({ session_id: null, seq: 0, type: 'session.closure', data: { session_id: 's1', closure } }),
    })
    const store = useClosureStore()
    expect(store.closures.s1?.verdict).toBe('can_close')
    sockets[0]!.onclose?.({})
    vi.advanceTimersByTime(10)
    sockets[1]!.onopen?.({})
    expect(store.epoch).toBe(1)
    expect('s1' in store.closures).toBe(false)
  })

  it('leva delivery.updated ao store de entregas e recarrega o dia ao reconectar', async () => {
    const sockets: FakeSocket[] = []
    const socket = new EventSocket({ url: 'ws://x/ws', createSocket: () => { const s = new FakeSocket(); sockets.push(s); return s }, initialDelay: 10 })
    const fetchMock = vi.fn(async (url: string) =>
      url === '/api/deliveries?date=2026-10-07'
        ? jsonResponse({ date: '2026-10-07', agent_enabled: true, deliveries: [], in_progress: [] })
        : jsonResponse([]),
    )
    vi.stubGlobal('fetch', fetchMock)
    const store = useDeliveriesStore()
    store.day = {
      date: '2026-10-07', agent_enabled: true, in_progress: [], prev_day: null, next_day: null,
      deliveries: [{ id: 1, session_id: 's1', project_id: 1, project_name: 'app', title: 'T', finished_at: 5, status: 'pending', summary_title: null, bullets: [], error: null }],
    }
    store.date = '2026-10-07'
    bindRealtime(socket)
    socket.connect()
    sockets[0]!.onopen?.({})
    const updated = { id: 1, session_id: 's1', project_id: 1, project_name: 'app', title: 'T', finished_at: 5, status: 'done', summary_title: 'Feito', bullets: ['a'], error: null }
    sockets[0]!.onmessage?.({
      data: JSON.stringify({ session_id: null, seq: 0, type: 'delivery.updated', data: updated }),
    })
    expect(store.day?.deliveries[0]?.summary_title).toBe('Feito')
    sockets[0]!.onclose?.({})
    vi.advanceTimersByTime(10)
    sockets[1]!.onopen?.({})
    await flushPromises()
    expect(fetchMock).toHaveBeenCalledWith('/api/deliveries?date=2026-10-07', expect.anything())
    expect(store.day?.deliveries).toEqual([])
  })

  it('relê o estado do agente de resumos ao reconectar', async () => {
    const sockets: FakeSocket[] = []
    const socket = new EventSocket({ url: 'ws://x/ws', createSocket: () => { const s = new FakeSocket(); sockets.push(s); return s }, initialDelay: 10 })
    const status = { enabled: true, running: true, next_run_at: 50, paused_until: null }
    const fetchMock = vi.fn(async (url: string) =>
      url === '/api/digest/config' ? jsonResponse({ config: {}, status }) : jsonResponse([]),
    )
    vi.stubGlobal('fetch', fetchMock)
    const store = useDigestStore()
    store.applyStatus({ enabled: true, running: false, next_run_at: null, paused_until: null })
    bindRealtime(socket)
    socket.connect()
    sockets[0]!.onopen?.({})
    sockets[0]!.onclose?.({})
    vi.advanceTimersByTime(10)
    sockets[1]!.onopen?.({})
    await flushPromises()
    expect(fetchMock).toHaveBeenCalledWith('/api/digest/config', expect.anything())
    expect(store.status).toEqual(status)
  })

  it('ignora a falha ao reler o estado do agente ao reconectar', async () => {
    const sockets: FakeSocket[] = []
    const socket = new EventSocket({ url: 'ws://x/ws', createSocket: () => { const s = new FakeSocket(); sockets.push(s); return s }, initialDelay: 10 })
    vi.stubGlobal('fetch', vi.fn(async (url: string) =>
      url === '/api/digest/config' ? new Response('x', { status: 500 }) : jsonResponse([]),
    ))
    const store = useDigestStore()
    const before = { enabled: true, running: false, next_run_at: null, paused_until: null }
    store.applyStatus(before)
    bindRealtime(socket)
    socket.connect()
    sockets[0]!.onopen?.({})
    sockets[0]!.onclose?.({})
    vi.advanceTimersByTime(10)
    sockets[1]!.onopen?.({})
    await flushPromises()
    expect(store.status).toEqual(before)
  })

  it('leva session.state e session.title ao store e recarrega ao reconectar', async () => {
    const sockets: FakeSocket[] = []
    const socket = new EventSocket({
      url: 'ws://x/ws',
      createSocket: () => {
        const s = new FakeSocket()
        sockets.push(s)
        return s
      },
      initialDelay: 10,
    })
    const sessions = useSessionsStore()
    const projects = useProjectsStore()
    projects.projects = [makeProject({ id: 1 })]
    sessions.setForProject(1, [makeSession({ session_id: 'a' })])

    bindRealtime(socket)
    socket.connect()
    sockets[0]!.onopen?.({})

    sockets[0]!.onmessage?.({
      data: JSON.stringify({ session_id: 'a', seq: 1, type: 'session.state', data: { state: 'running', error: null } }),
    })
    sockets[0]!.onmessage?.({
      data: JSON.stringify({ session_id: 'a', seq: 2, type: 'session.title', data: { title: 'Olá' } }),
    })
    expect(sessions.find('a')).toMatchObject({ state: 'running', title: 'Olá' })

    const fetchMock = vi.fn(async (url: string) =>
      url === '/api/projects'
        ? jsonResponse([makeProject({ id: 1 })])
        : jsonResponse([makeSession({ session_id: 'a', state: 'idle', title: 'Olá' })]),
    )
    vi.stubGlobal('fetch', fetchMock)
    sockets[0]!.onclose?.({})
    vi.advanceTimersByTime(10)
    sockets[1]!.onopen?.({})
    await flushPromises()

    expect(fetchMock).toHaveBeenCalledWith('/api/projects', expect.anything())
    expect(fetchMock).toHaveBeenCalledWith('/api/projects/1/sessions', expect.anything())
    expect(sessions.find('a')?.state).toBe('idle')
    expect(fetchMock).toHaveBeenCalledWith('/api/models', expect.anything())
  })

  it('project.synced recarrega as sessões do projeto', async () => {
    const sockets: FakeSocket[] = []
    const socket = new EventSocket({ url: 'ws://x/ws', createSocket: () => { const s = new FakeSocket(); sockets.push(s); return s }, initialDelay: 10 })
    const sessions = useSessionsStore()
    sessions.setForProject(2, [])
    const fetchMock = vi.fn(async (url: string) =>
      url === '/api/projects'
        ? jsonResponse([makeProject({ id: 2, hidden_sessions: 4 })])
        : jsonResponse([makeSession({ session_id: 'z', project_id: 2, title: 'Sincronizada' })]),
    )
    vi.stubGlobal('fetch', fetchMock)
    bindRealtime(socket)
    socket.connect()
    sockets[0]!.onopen?.({})
    sockets[0]!.onmessage?.({ data: JSON.stringify({ session_id: null, seq: 0, type: 'project.synced', data: { project_id: 2 } }) })
    await flushPromises()
    expect(fetchMock).toHaveBeenCalledWith('/api/projects/2/sessions', expect.anything())
    expect(sessions.find('z')?.title).toBe('Sincronizada')
  })

  it('groups.changed recarrega os agrupadores', async () => {
    const sockets: FakeSocket[] = []
    const socket = new EventSocket({ url: 'ws://x/ws', createSocket: () => { const s = new FakeSocket(); sockets.push(s); return s }, initialDelay: 10 })
    const fetchMock = vi.fn(async () => jsonResponse([makeGroup({ id: 7, project_id: 2 })]))
    vi.stubGlobal('fetch', fetchMock)
    bindRealtime(socket)
    socket.connect()
    sockets[0]!.onopen?.({})
    sockets[0]!.onmessage?.({ data: JSON.stringify({ session_id: null, seq: 0, type: 'groups.changed', data: { project_id: 2 } }) })
    await flushPromises()
    expect(fetchMock).toHaveBeenCalledWith('/api/groups', expect.anything())
    expect(useGroupsStore().byId(7)?.project_id).toBe(2)
  })

  it('loadEverything também carrega os agrupadores', async () => {
    const fetchMock = vi.fn(async (url: string) => {
      if (url === '/api/projects') return jsonResponse([makeProject({ id: 1 })])
      if (url === '/api/groups') return jsonResponse([makeGroup({ id: 3 })])
      return jsonResponse([])
    })
    vi.stubGlobal('fetch', fetchMock)
    await loadEverything()
    await flushPromises()
    expect(fetchMock).toHaveBeenCalledWith('/api/groups', expect.anything())
    expect(useGroupsStore().byId(3)).toBeDefined()
  })

  it('labels.changed recarrega o catálogo de etiquetas', async () => {
    const sockets: FakeSocket[] = []
    const socket = new EventSocket({ url: 'ws://x/ws', createSocket: () => { const s = new FakeSocket(); sockets.push(s); return s }, initialDelay: 10 })
    const fetchMock = vi.fn(async () => jsonResponse([makeLabel({ id: 7, slug: 'urgente' })]))
    vi.stubGlobal('fetch', fetchMock)
    bindRealtime(socket)
    socket.connect()
    sockets[0]!.onopen?.({})
    sockets[0]!.onmessage?.({ data: JSON.stringify({ session_id: null, seq: 0, type: 'labels.changed', data: {} }) })
    await flushPromises()
    expect(fetchMock).toHaveBeenCalledWith('/api/labels', expect.anything())
    expect(useLabelsStore().byId(7)?.slug).toBe('urgente')
  })

  it('loadEverything também carrega as etiquetas', async () => {
    const fetchMock = vi.fn(async (url: string) => {
      if (url === '/api/projects') return jsonResponse([makeProject({ id: 1 })])
      if (url === '/api/labels') return jsonResponse([makeLabel({ id: 3 })])
      return jsonResponse([])
    })
    vi.stubGlobal('fetch', fetchMock)
    await loadEverything()
    await flushPromises()
    expect(fetchMock).toHaveBeenCalledWith('/api/labels', expect.anything())
    expect(useLabelsStore().byId(3)).toBeDefined()
  })

  it('loadEverything também carrega os agentes, os avisos e as decisões pendentes', async () => {
    const fetchMock = vi.fn(async (url: string) => {
      if (url === '/api/projects') return jsonResponse([makeProject({ id: 1 })])
      if (url === '/api/agents') return jsonResponse([makeAgent({ id: 1, name: 'Triagem' })])
      if (url === '/api/agent-notices') return jsonResponse([makeNotice({ id: 5 })])
      return jsonResponse([])
    })
    vi.stubGlobal('fetch', fetchMock)
    await loadEverything()
    await flushPromises()
    expect(fetchMock).toHaveBeenCalledWith('/api/agents', expect.anything())
    expect(fetchMock).toHaveBeenCalledWith('/api/agent-notices', expect.anything())
    expect(useOrgStore().byId(1)?.name).toBe('Triagem')
    expect(useOrgStore().unreadCount).toBe(1)
    expect(fetchMock).toHaveBeenCalledWith('/api/decisions?pending=true', expect.anything())
  })

  it('loadEverything segue quando a lista de agentes falha', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (url === '/api/projects') return jsonResponse([makeProject({ id: 1 })])
      if (url === '/api/agents') return jsonResponse({ detail: 'x' }, 500)
      if (url === '/api/agent-notices') return jsonResponse([makeNotice({ id: 5 })])
      return jsonResponse([])
    }))
    await expect(loadEverything()).resolves.toBeUndefined()
    await flushPromises()
    expect(useOrgStore().unreadCount).toBe(1)
  })

  it('ao reconectar, relê agentes e avisos uma vez só', async () => {
    const sockets: FakeSocket[] = []
    const socket = new EventSocket({ url: 'ws://x/ws', createSocket: () => { const s = new FakeSocket(); sockets.push(s); return s }, initialDelay: 10 })
    const fetchMock = vi.fn(async (url: string) => {
      if (url === '/api/projects') return jsonResponse([makeProject({ id: 1 })])
      return jsonResponse([])
    })
    vi.stubGlobal('fetch', fetchMock)
    bindRealtime(socket)
    socket.connect()
    sockets[0]!.onopen?.({})
    sockets[0]!.onclose?.({})
    vi.advanceTimersByTime(10)
    sockets[1]!.onopen?.({})
    await flushPromises()
    const count = (path: string) => fetchMock.mock.calls.filter(([u]) => u === path).length
    expect(count('/api/agents')).toBe(1)
    expect(count('/api/agent-notices')).toBe(1)
  })

  const CLAUDE_STATE = {
    in_use: { source: 'system', version: '2.1.294' },
    system: { path: '/opt/bin/claude', version: '2.1.294' },
    bundled: { version: '2.1.284' },
    forced_bundled: false,
    can_update: true,
    job: null,
    latest: { version: '2.1.296', channel: 'latest', checked_at: 5 },
    update_available: true,
  }

  it('claude_cli.state aplica o estado na store do Claude', () => {
    const sockets: FakeSocket[] = []
    const socket = new EventSocket({ url: 'ws://x/ws', createSocket: () => { const s = new FakeSocket(); sockets.push(s); return s }, initialDelay: 10 })
    bindRealtime(socket)
    socket.connect()
    sockets[0]!.onopen?.({})
    sockets[0]!.onmessage?.({ data: JSON.stringify({ session_id: null, seq: 0, type: 'claude_cli.state', data: CLAUDE_STATE }) })
    expect(useClaudeCliStore().info?.update_available).toBe(true)
    expect(useClaudeCliStore().info?.latest?.version).toBe('2.1.296')
  })

  it('loadEverything carrega o estado do Claude', async () => {
    const fetchMock = vi.fn(async (url: string) => {
      if (url === '/api/claude-cli') return jsonResponse(CLAUDE_STATE)
      if (url === '/api/projects') return jsonResponse([])
      return jsonResponse([])
    })
    vi.stubGlobal('fetch', fetchMock)
    await loadEverything()
    await flushPromises()
    expect(fetchMock).toHaveBeenCalledWith('/api/claude-cli', expect.anything())
    expect(useClaudeCliStore().info?.update_available).toBe(true)
  })

  it('leva project.git ao store git', () => {
    const sockets: FakeSocket[] = []
    const socket = new EventSocket({ url: 'ws://x/ws', createSocket: () => { const s = new FakeSocket(); sockets.push(s); return s } })
    bindRealtime(socket)
    socket.connect()
    sockets[0]!.onopen?.({})
    sockets[0]!.onmessage?.({
      data: JSON.stringify({ session_id: null, seq: 0, type: 'project.git', data: { project_id: 1, repos: [{ rel_path: '.', branch: 'dev' }] } }),
    })
    expect(useGitStore().reposFor(1)[0]?.branch).toBe('dev')
  })

  it('models.updated troca a lista de modelos', () => {
    const sockets: FakeSocket[] = []
    const socket = new EventSocket({ url: 'ws://x/ws', createSocket: () => { const s = new FakeSocket(); sockets.push(s); return s } })
    bindRealtime(socket)
    socket.connect()
    sockets[0]!.onopen?.({})
    const models = [{ value: 'x', displayName: 'X', description: 'd', supportsEffort: false, supportedEffortLevels: [] }]
    sockets[0]!.onmessage?.({ data: JSON.stringify({ session_id: null, seq: 0, type: 'models.updated', data: { models } }) })
    expect(useModelsStore().models.map((m) => m.value)).toEqual(['x'])
  })
  it('leva os eventos da organização (agent.*, task, decision) às stores novas', async () => {
    const sockets: FakeSocket[] = []
    const socket = new EventSocket({ url: 'ws://x/ws', createSocket: () => { const s = new FakeSocket(); sockets.push(s); return s } })
    const fetchMock = vi.fn(async (url: string) => {
      if (url === '/api/agents/1') return jsonResponse(makeAgent({ name: 'Do servidor', unseen: 4 }))
      if (url === '/api/tasks/3') return jsonResponse(makeTaskDetail({ task: makeTask({ id: 3, revision: 7 }) }))
      return jsonResponse([])
    })
    vi.stubGlobal('fetch', fetchMock)
    bindRealtime(socket)
    socket.connect()
    sockets[0]!.onopen?.({})
    const send = (type: string, data: unknown) => sockets[0]!.onmessage?.({ data: JSON.stringify({ session_id: null, seq: 0, type, data }) })
    const org = useOrgStore()
    const tasks = useTasksStore()
    org.agents = [makeAgent()]

    send('agent.run', makeRun({ id: 4, outcome: 'waiting' }))
    expect(org.byId(1)?.last_run?.outcome).toBe('waiting')
    send('agent.notice', makeNotice({ id: 9 }))
    expect(org.unreadCount).toBe(1)
    send('agent.notice', { read_ids: [9] })
    expect(org.unreadCount).toBe(0)
    send('agent.changed', { id: 1 })
    await vi.waitFor(() => expect(org.byId(1)?.name).toBe('Do servidor'))
    org.agents = [makeAgent({ unseen: 0 })]
    send('agent.announcement', { id: 1, agent_id: 1, run_id: 4, session_id: 's', text: 'ok', created_at: 1, delivered_at: null })
    await vi.waitFor(() => expect(org.byId(1)?.unseen).toBe(4))
    send('decision', makeDecision({ id: 6 }))
    expect(org.decisionsPending.map((d) => d.id)).toEqual([6])

    await tasks.detail(3)
    const version = tasks.version
    send('task', { id: 3, project_id: 1, status: 'done', revision: 7, change: 'status' })
    expect(tasks.version).toBe(version + 1)
    await vi.waitFor(() => expect(tasks.details[3]?.task.revision).toBe(7))
    send('decision', makeDecision({ id: 6, task_id: 3, status: 'answered' }))
    expect(org.decisionsPending).toEqual([])
  })

  it('os eventos work.* e specialist.* não têm mais ouvinte', () => {
    const sockets: FakeSocket[] = []
    const socket = new EventSocket({ url: 'ws://x/ws', createSocket: () => { const s = new FakeSocket(); sockets.push(s); return s } })
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse([])))
    bindRealtime(socket)
    socket.connect()
    sockets[0]!.onopen?.({})
    const fetchMock = vi.mocked(fetch)
    for (const type of ['work.changed', 'work.mode', 'work.notification', 'work.decision', 'specialist.changed', 'specialist.run']) {
      sockets[0]!.onmessage?.({ data: JSON.stringify({ session_id: null, seq: 0, type, data: { id: 1 } }) })
    }
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('ao reconectar, deixa as tarefas velhas e relê decisões pendentes', async () => {
    const sockets: FakeSocket[] = []
    const socket = new EventSocket({ url: 'ws://x/ws', createSocket: () => { const s = new FakeSocket(); sockets.push(s); return s }, initialDelay: 10 })
    const fetchMock = vi.fn(async (url: string) => {
      if (url === '/api/projects') return jsonResponse([makeProject({ id: 1 })])
      if (url === '/api/tasks?project_id=1') return jsonResponse([makeTask()])
      if (url === '/api/decisions?pending=true') return jsonResponse([makeDecision({ id: 3 })])
      return jsonResponse([])
    })
    vi.stubGlobal('fetch', fetchMock)
    const tasks = useTasksStore()
    await tasks.list({ project_id: 1 })
    bindRealtime(socket)
    socket.connect()
    sockets[0]!.onopen?.({})
    sockets[0]!.onclose?.({})
    vi.advanceTimersByTime(10)
    sockets[1]!.onopen?.({})
    await flushPromises()
    expect(useOrgStore().decisionsPending.map((d) => d.id)).toEqual([3])
    await tasks.list({ project_id: 1 })
    expect(fetchMock.mock.calls.filter(([u]) => u === '/api/tasks?project_id=1')).toHaveLength(2)
  })
})
