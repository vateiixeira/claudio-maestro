import type { Session, SessionState } from './api'

// Envelope sent by the backend over WS /ws. Every session shares the same socket.
export interface WsEvent<TData = unknown> {
  session_id: string
  seq: number
  type: string
  data: TData
}

export interface SessionStateData {
  state: SessionState
  error: string | null
}

export interface SessionTitleData {
  title: string
}

export type SessionStateEvent = WsEvent<SessionStateData> & { type: 'session.state' }
export type SessionTitleEvent = WsEvent<SessionTitleData> & { type: 'session.title' }

/** `session.updated` carries the whole session, as the listings return it. */
export type SessionUpdatedEvent = WsEvent<Session> & { type: 'session.updated' }

export type ConnectionStatus = 'idle' | 'connecting' | 'connected' | 'reconnecting'
