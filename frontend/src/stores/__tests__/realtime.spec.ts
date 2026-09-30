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
import { useDigestStore } from '../digest'
import { jsonResponse, makeGroup, makeProject, makeSession } from '../../test/factories'

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
})
