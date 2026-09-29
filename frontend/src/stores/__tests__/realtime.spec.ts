import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { EventSocket, type SocketLike } from '../../api/socket'
import { bindRealtime } from '../realtime'
import { useSessionsStore } from '../sessions'
import { useProjectsStore } from '../projects'
import { useGitStore } from '../git'
import { jsonResponse, makeProject, makeSession } from '../../test/factories'

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
})
