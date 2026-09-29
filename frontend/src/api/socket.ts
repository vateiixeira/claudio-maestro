import { ref, type Ref } from 'vue'
import type { ConnectionStatus, WsEvent } from '../types/events'

/** The subset of the browser WebSocket this client uses; tests pass a fake. */
export interface SocketLike {
  onopen: ((ev: never) => void) | null
  onclose: ((ev: never) => void) | null
  onerror: ((ev: never) => void) | null
  onmessage: ((ev: { data: unknown }) => void) | null
  close(): void
}

export interface EventSocketOptions {
  url: string
  createSocket?: (url: string) => SocketLike
  /** First wait before reconnecting, in ms. Doubles on each failure. */
  initialDelay?: number
  /** Upper bound for the wait, in ms. */
  maxDelay?: number
}

export type EventHandler = (event: WsEvent) => void
type Unsubscribe = () => void

function addTo<K, V>(map: Map<K, Set<V>>, key: K, value: V): Unsubscribe {
  let set = map.get(key)
  if (!set) {
    set = new Set()
    map.set(key, set)
  }
  set.add(value)
  return () => {
    set.delete(value)
    if (set.size === 0) map.delete(key)
  }
}

function isEvent(value: unknown): value is WsEvent {
  if (!value || typeof value !== 'object') return false
  const v = value as Record<string, unknown>
  // Project events (`project.synced`) carry `session_id: null`.
  return typeof v.type === 'string' && (typeof v.session_id === 'string' || v.session_id === null)
}

/**
 * Receive-only client for WS /ws. Reconnects by itself with a growing wait and
 * tells `onReconnect` subscribers so they can reload what they show.
 */
export class EventSocket {
  readonly status: Ref<ConnectionStatus> = ref('idle')

  private readonly url: string
  private readonly createSocket: (url: string) => SocketLike
  private readonly initialDelay: number
  private readonly maxDelay: number

  private socket: SocketLike | null = null
  private timer: ReturnType<typeof setTimeout> | null = null
  private delay: number
  private wasDropped = false
  private stopped = true

  private readonly byType = new Map<string, Set<EventHandler>>()
  private readonly bySession = new Map<string, Set<EventHandler>>()
  private readonly anyHandlers = new Set<EventHandler>()
  private readonly reconnectHandlers = new Set<() => void>()

  constructor(options: EventSocketOptions) {
    this.url = options.url
    this.createSocket = options.createSocket ?? ((url) => new WebSocket(url) as unknown as SocketLike)
    this.initialDelay = options.initialDelay ?? 500
    this.maxDelay = options.maxDelay ?? 5000
    this.delay = this.initialDelay
  }

  connect(): void {
    if (!this.stopped) return
    this.stopped = false
    this.open()
  }

  close(): void {
    this.stopped = true
    if (this.timer) clearTimeout(this.timer)
    this.timer = null
    const socket = this.socket
    this.socket = null
    socket?.close()
    this.status.value = 'idle'
  }

  /** Events of one type, e.g. `session.state`. */
  on(type: string, handler: EventHandler): Unsubscribe {
    return addTo(this.byType, type, handler)
  }

  /** Every event of one session. */
  onSession(sessionId: string, handler: EventHandler): Unsubscribe {
    return addTo(this.bySession, sessionId, handler)
  }

  onAny(handler: EventHandler): Unsubscribe {
    this.anyHandlers.add(handler)
    return () => this.anyHandlers.delete(handler)
  }

  /** Called after the socket comes back from a drop. Events sent meanwhile were lost. */
  onReconnect(handler: () => void): Unsubscribe {
    this.reconnectHandlers.add(handler)
    return () => this.reconnectHandlers.delete(handler)
  }

  private open(): void {
    this.status.value = this.wasDropped ? 'reconnecting' : 'connecting'
    const socket = this.createSocket(this.url)
    this.socket = socket

    socket.onopen = () => {
      if (socket !== this.socket) return
      this.delay = this.initialDelay
      this.status.value = 'connected'
      if (this.wasDropped) this.reconnectHandlers.forEach((handler) => handler())
    }

    socket.onmessage = (message) => {
      if (socket !== this.socket) return
      this.dispatch(message.data)
    }

    socket.onclose = () => {
      if (socket !== this.socket || this.stopped) return
      this.socket = null
      this.scheduleReconnect()
    }
  }

  private scheduleReconnect(): void {
    // A failed first attempt also counts as a drop: the user needs to see it.
    this.wasDropped = true
    this.status.value = 'reconnecting'
    const wait = this.delay
    this.delay = Math.min(this.delay * 2, this.maxDelay)
    this.timer = setTimeout(() => {
      this.timer = null
      if (!this.stopped) this.open()
    }, wait)
  }

  private dispatch(raw: unknown): void {
    let event: unknown
    try {
      event = typeof raw === 'string' ? JSON.parse(raw) : raw
    } catch {
      return
    }
    if (!isEvent(event)) return
    this.byType.get(event.type)?.forEach((handler) => handler(event))
    this.bySession.get(event.session_id)?.forEach((handler) => handler(event))
    this.anyHandlers.forEach((handler) => handler(event))
  }
}

let shared: EventSocket | null = null

/** The app-wide socket, pointed at /ws on the page's own host. */
export function useEventSocket(): EventSocket {
  if (!shared) {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    shared = new EventSocket({ url: `${protocol}//${window.location.host}/ws` })
  }
  return shared
}
