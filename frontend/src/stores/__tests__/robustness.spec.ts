import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { EventSocket, type SocketLike } from '../../api/socket'
import { useConversationStore } from '../conversation'
import { useLayoutStore } from '../layout'
import { bindRealtime } from '../realtime'
import { useSessionsStore } from '../sessions'
import { jsonResponse, makeEvent, makeSession, makeSnapshot, routeFetch } from '../../test/factories'

const text = (id: string, t: string, streaming = false) => ({
  type: 'text', id, text: t, streaming, parent_tool_use_id: null,
})

class FakeSocket implements SocketLike {
  onopen: ((ev: unknown) => void) | null = null
  onclose: ((ev: unknown) => void) | null = null
  onerror: ((ev: unknown) => void) | null = null
  onmessage: ((ev: { data: unknown }) => void) | null = null
  close() {}
}

function makeSocket() {
  const sockets: FakeSocket[] = []
  const socket = new EventSocket({
    url: 'ws://x/ws',
    createSocket: () => { const s = new FakeSocket(); sockets.push(s); return s },
    initialDelay: 10,
  })
  return { socket, sockets }
}

beforeEach(() => setActivePinia(createPinia()))
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('recarregar no meio de uma resposta', () => {
  it('o retrato traz o texto parcial e a permissão pendente, e os eventos seguintes continuam dele', async () => {
    const prompt = { prompt_id: 'p1', tool_name: 'Bash', input: { command: 'ls' }, can_always: true }
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/sessions/s1': () => jsonResponse(makeSnapshot({
        seq: 7, state: 'awaiting_decision', items: [text('a', 'Parcial', true) as never], prompts: [prompt as never],
      })),
    }))
    const store = useConversationStore()
    await store.load('s1')
    store.receive(makeEvent('item.append', { item_id: 'a', text: ' e mais' }, 8))
    const conv = store.get('s1')!
    expect((conv.items[0] as { text: string }).text).toBe('Parcial e mais')
    expect(conv.prompts.map((p) => p.prompt_id)).toEqual(['p1'])
    expect(conv.state).toBe('awaiting_decision')
  })
})

describe('salto de seq', () => {
  it('evento com seq pulado recarrega o retrato', async () => {
    let calls = 0
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/sessions/s1': () => {
        calls += 1
        return jsonResponse(calls === 1
          ? makeSnapshot({ seq: 2, items: [text('a', 'um') as never] })
          : makeSnapshot({ seq: 5, items: [text('a', 'um'), text('b', 'dois'), text('c', 'três')] as never }))
      },
    }))
    const store = useConversationStore()
    await store.load('s1')
    store.receive(makeEvent('item.upsert', text('c', 'três'), 5))
    await flushPromises()
    expect(calls).toBe(2)
    expect(store.get('s1')!.items.map((i) => i.id)).toEqual(['a', 'b', 'c'])
  })

  it('evento seguinte não recarrega', async () => {
    let calls = 0
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/sessions/s1': () => { calls += 1; return jsonResponse(makeSnapshot({ seq: 2 })) },
    }))
    const store = useConversationStore()
    await store.load('s1')
    store.receive(makeEvent('item.upsert', text('c', 'x'), 3))
    await flushPromises()
    expect(calls).toBe(1)
  })

  it('a socket avisa em toda abertura, inclusive a primeira', () => {
    const { socket, sockets } = makeSocket()
    const opened = vi.fn()
    socket.onOpen(opened)
    socket.connect()
    sockets[0]!.onopen?.({})
    expect(opened).toHaveBeenCalledTimes(1)
  })
})

describe('layout na reconexão', () => {
  it('lê de novo o layout se a primeira leitura falhou, e volta a salvar', async () => {
    vi.useFakeTimers()
    let fail = true
    const puts: unknown[] = []
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/state': () => (fail ? jsonResponse({ detail: 'x' }, 500) : jsonResponse({ layout: { columns: ['a'], widths: {} } })),
      'PUT /api/state/layout': (init) => { puts.push(JSON.parse(init!.body as string)); return jsonResponse({}) },
      'GET /api/projects': () => jsonResponse([]),
      'GET /api/models': () => jsonResponse([]),
    }))
    const layout = useLayoutStore()
    await layout.restore()
    layout.open('b')
    await vi.advanceTimersByTimeAsync(600)
    expect(puts).toHaveLength(0)

    fail = false
    const { socket, sockets } = makeSocket()
    bindRealtime(socket)
    socket.connect()
    sockets[0]!.onclose?.({})
    await vi.advanceTimersByTimeAsync(10)
    sockets[1]!.onopen?.({})
    await vi.advanceTimersByTimeAsync(600)
    expect(layout.columns).toEqual(['a', 'b'])
    expect(puts.at(-1)).toMatchObject({ columns: ['a', 'b'] })
  })
})

describe('sessão criada em outra aba', () => {
  it('session.state de sessão desconhecida busca e insere a sessão', async () => {
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/sessions/n1': () => jsonResponse(makeSnapshot({ session_id: 'n1', project_id: 1 })),
      'GET /api/projects/1/sessions': () => jsonResponse([makeSession({ session_id: 'n1', project_id: 1, title: 'Nova' })]),
    }))
    const sessions = useSessionsStore()
    sessions.setForProject(1, [])
    sessions.applyEvent(makeEvent('session.state', { state: 'running', error: null }, 1, 'n1'))
    await flushPromises()
    expect(sessions.find('n1')?.title).toBe('Nova')
  })

  it('listagem enviada antes da criação não remove a sessão criada', async () => {
    let release!: (r: Response) => void
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/projects/1/sessions': () => new Promise<Response>((r) => { release = r }),
      'POST /api/projects/1/sessions': () => jsonResponse(makeSession({ session_id: 'n1', project_id: 1 }), 201),
    }))
    const sessions = useSessionsStore()
    sessions.setForProject(1, [makeSession({ session_id: 'old', project_id: 1 })])
    const listing = sessions.loadForProject(1)
    await sessions.create(1)
    release(jsonResponse([makeSession({ session_id: 'old', project_id: 1 })]))
    await listing
    expect(sessions.forProject(1).map((s) => s.session_id)).toEqual(['n1', 'old'])
  })

  it('o mesmo vale para loadAll e para session.updated', async () => {
    let release!: (r: Response) => void
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/projects/1/sessions': () => new Promise<Response>((r) => { release = r }),
    }))
    const sessions = useSessionsStore()
    const all = sessions.loadAll([1])
    sessions.applyEvent(makeEvent('session.updated', makeSession({ session_id: 'n1', project_id: 1 }), 1, 'n1'))
    release(jsonResponse([]))
    await all
    expect(sessions.forProject(1).map((s) => s.session_id)).toEqual(['n1'])
  })

  it('listagem enviada depois da criação vale como está', async () => {
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/projects/1/sessions': () => jsonResponse([]),
    }))
    const sessions = useSessionsStore()
    sessions.applyEvent(makeEvent('session.updated', makeSession({ session_id: 'n1', project_id: 1 }), 1, 'n1'))
    await sessions.loadForProject(1)
    expect(sessions.forProject(1)).toEqual([])
  })
})

describe('duas abas', () => {
  it('estado, título e finalizada de outra aba chegam à lista', () => {
    const sessions = useSessionsStore()
    sessions.setForProject(1, [makeSession({ session_id: 's1', project_id: 1 })])
    sessions.applyEvent(makeEvent('session.updated', makeSession({ session_id: 's1', project_id: 1, title: 'Outro', finished: true, display_state: 'finished' }), 1))
    expect(sessions.find('s1')).toMatchObject({ title: 'Outro', finished: true })
  })

  it('prompt.resolved vindo de outra aba some com o cartão', async () => {
    const prompt = { prompt_id: 'p1', tool_name: 'Bash', input: {}, can_always: false }
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/sessions/s1': () => jsonResponse(makeSnapshot({ seq: 1, prompts: [prompt as never] })),
    }))
    const store = useConversationStore()
    await store.load('s1')
    store.receive(makeEvent('prompt.resolved', { prompt_id: 'p1', decision: 'allow' }, 2))
    expect(store.get('s1')!.prompts).toEqual([])
  })
})

describe('primeira abertura da socket', () => {
  it('bindRealtime não recarrega tudo na primeira abertura', async () => {
    const fetchMock = vi.fn(async () => jsonResponse([]))
    vi.stubGlobal('fetch', fetchMock)
    const { socket, sockets } = makeSocket()
    bindRealtime(socket)
    socket.connect()
    sockets[0]!.onopen?.({})
    await flushPromises()
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
