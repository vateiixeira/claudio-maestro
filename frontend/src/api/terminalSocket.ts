import type { SocketLike } from './socket'

/** What the server sends on WS /ws/terminal/{session_id}. */
export type TerminalFrame =
  | { type: 'replay'; data: string; cols: number; rows: number }
  | { type: 'output'; data: string }
  | { type: 'busy'; busy: boolean }
  | { type: 'run'; run_id: string; state: 'running' | 'sent' | 'interrupted' | 'failed'; exit_code: number | null }
  | { type: 'exit' }

/** The browser socket as this client uses it: the receive-only subset plus `send`. */
export type TerminalSocketLike = SocketLike & { send(data: string): void }

const CONNECTING = 0
const FRAME_TYPES = new Set(['replay', 'output', 'busy', 'run', 'exit'])

function isFrame(value: unknown): value is TerminalFrame {
  return typeof value === 'object' && value !== null && FRAME_TYPES.has((value as { type?: unknown }).type as string)
}

/**
 * Client for one session's terminal. It never reconnects by itself: whoever
 * wants a new connection builds a new one (the store does it on `connect`).
 */
export class TerminalSocket {
  private readonly socket: TerminalSocketLike
  private readonly frameHandlers = new Set<(frame: TerminalFrame) => void>()
  private readonly closeHandlers = new Set<(code: number) => void>()
  // What was sent while the socket was still connecting, in order.
  private queued: string[] = []
  private closed = false

  constructor(sessionId: string, createSocket?: (url: string) => TerminalSocketLike) {
    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const url = `${protocol}://${window.location.host}/ws/terminal/${encodeURIComponent(sessionId)}`
    const socket = (createSocket ?? ((u: string) => new WebSocket(u) as unknown as TerminalSocketLike))(url)
    this.socket = socket

    socket.onopen = () => {
      const queued = this.queued
      this.queued = []
      queued.forEach((message) => this.socket.send(message))
    }
    socket.onmessage = (message) => this.dispatch(message.data)
    socket.onclose = (event: { code?: number } | undefined) => {
      this.queued = []
      const code = typeof event?.code === 'number' ? event.code : 1006
      this.closeHandlers.forEach((handler) => handler(code))
    }
  }

  onFrame(cb: (frame: TerminalFrame) => void): () => void {
    this.frameHandlers.add(cb)
    return () => this.frameHandlers.delete(cb)
  }

  onClose(cb: (code: number) => void): () => void {
    this.closeHandlers.add(cb)
    return () => this.closeHandlers.delete(cb)
  }

  sendInput(data: string): void {
    this.send({ type: 'input', data })
  }

  resize(cols: number, rows: number): void {
    this.send({ type: 'resize', cols, rows })
  }

  close(): void {
    this.closed = true
    this.queued = []
    this.socket.close()
  }

  private send(message: object): void {
    if (this.closed) return
    const raw = JSON.stringify(message)
    // A browser socket throws if it sends before opening; hold the message until then.
    if ((this.socket as { readyState?: number }).readyState === CONNECTING) {
      this.queued.push(raw)
      return
    }
    this.socket.send(raw)
  }

  private dispatch(raw: unknown): void {
    let frame: unknown
    try {
      frame = typeof raw === 'string' ? JSON.parse(raw) : raw
    } catch {
      return
    }
    if (!isFrame(frame)) return
    this.frameHandlers.forEach((handler) => handler(frame))
  }
}
