import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { EventSocket, type SocketLike } from '../socket'

class FakeSocket implements SocketLike {
  onopen: ((ev: unknown) => void) | null = null
  onclose: ((ev: unknown) => void) | null = null
  onerror: ((ev: unknown) => void) | null = null
  onmessage: ((ev: { data: unknown }) => void) | null = null
  closed = false
  url: string

  constructor(url: string) {
    this.url = url
  }

  open() {
    this.onopen?.({})
  }

  emit(event: object) {
    this.onmessage?.({ data: JSON.stringify(event) })
  }

  drop() {
    this.onclose?.({})
  }

  close() {
    this.closed = true
    this.onclose?.({})
  }
}

let sockets: FakeSocket[]

function build(options: Partial<ConstructorParameters<typeof EventSocket>[0]> = {}) {
  return new EventSocket({
    url: 'ws://localhost:6600/ws',
    createSocket: (url) => {
      const socket = new FakeSocket(url)
      sockets.push(socket)
      return socket
    },
    initialDelay: 500,
    maxDelay: 4000,
    ...options,
  })
}

function last(): FakeSocket {
  return sockets[sockets.length - 1]!
}

beforeEach(() => {
  sockets = []
  vi.useFakeTimers()
})

afterEach(() => vi.useRealTimers())

describe('EventSocket', () => {
  it('conecta na URL e informa o estado', () => {
    const client = build()
    expect(client.status.value).toBe('idle')
    client.connect()
    expect(last().url).toBe('ws://localhost:6600/ws')
    expect(client.status.value).toBe('connecting')
    last().open()
    expect(client.status.value).toBe('connected')
  })

  it('entrega eventos por tipo, por sessão e a todos', () => {
    const client = build()
    const byType = vi.fn()
    const bySession = vi.fn()
    const all = vi.fn()
    client.on('session.state', byType)
    client.onSession('s1', bySession)
    client.onAny(all)
    client.connect()
    last().open()

    const stateS1 = { session_id: 's1', seq: 1, type: 'session.state', data: { state: 'running', error: null } }
    const titleS2 = { session_id: 's2', seq: 1, type: 'session.title', data: { title: 'Oi' } }
    const itemS1 = { session_id: 's1', seq: 2, type: 'item.upsert', data: {} }
    last().emit(stateS1)
    last().emit(titleS2)
    last().emit(itemS1)

    expect(byType.mock.calls).toEqual([[stateS1]])
    expect(bySession.mock.calls).toEqual([[stateS1], [itemS1]])
    expect(all).toHaveBeenCalledTimes(3)
  })

  it('para de entregar depois de cancelar a assinatura', () => {
    const client = build()
    const handler = vi.fn()
    const off = client.on('session.title', handler)
    client.connect()
    last().open()
    off()
    last().emit({ session_id: 's1', seq: 1, type: 'session.title', data: { title: 'x' } })
    expect(handler).not.toHaveBeenCalled()
  })

  it('ignora mensagens que não são JSON', () => {
    const client = build()
    const handler = vi.fn()
    client.onAny(handler)
    client.connect()
    last().open()
    last().onmessage?.({ data: 'não é json' })
    expect(handler).not.toHaveBeenCalled()
  })

  it('reconecta após queda com espera crescente e limitada', () => {
    const client = build()
    client.connect()
    last().open()
    last().drop()
    expect(client.status.value).toBe('reconnecting')
    expect(sockets).toHaveLength(1)

    vi.advanceTimersByTime(499)
    expect(sockets).toHaveLength(1)
    vi.advanceTimersByTime(1)
    expect(sockets).toHaveLength(2)

    // Fails again without opening: the wait doubles.
    last().drop()
    vi.advanceTimersByTime(999)
    expect(sockets).toHaveLength(2)
    vi.advanceTimersByTime(1)
    expect(sockets).toHaveLength(3)

    last().drop()
    vi.advanceTimersByTime(2000)
    expect(sockets).toHaveLength(4)

    last().drop()
    vi.advanceTimersByTime(4000)
    expect(sockets).toHaveLength(5)

    // Capped at maxDelay.
    last().drop()
    vi.advanceTimersByTime(3999)
    expect(sockets).toHaveLength(5)
    vi.advanceTimersByTime(1)
    expect(sockets).toHaveLength(6)
  })

  it('volta à espera inicial depois de conectar', () => {
    const client = build()
    client.connect()
    last().drop()
    vi.advanceTimersByTime(500)
    last().drop()
    vi.advanceTimersByTime(1000)
    last().open()
    expect(client.status.value).toBe('connected')

    last().drop()
    vi.advanceTimersByTime(500)
    expect(sockets).toHaveLength(4)
  })

  it('avisa a reconexão, mas não a primeira conexão', () => {
    const client = build()
    const onReconnect = vi.fn()
    client.onReconnect(onReconnect)
    client.connect()
    last().open()
    expect(onReconnect).not.toHaveBeenCalled()

    last().drop()
    vi.advanceTimersByTime(500)
    expect(onReconnect).not.toHaveBeenCalled()
    last().open()
    expect(onReconnect).toHaveBeenCalledTimes(1)
    expect(client.status.value).toBe('connected')
  })

  it('não reconecta depois de fechado pelo app', () => {
    const client = build()
    client.connect()
    last().open()
    client.close()
    expect(last().closed).toBe(true)
    expect(client.status.value).toBe('idle')
    vi.advanceTimersByTime(10000)
    expect(sockets).toHaveLength(1)
  })

  it('connect repetido não abre outro socket', () => {
    const client = build()
    client.connect()
    client.connect()
    expect(sockets).toHaveLength(1)
  })
})
