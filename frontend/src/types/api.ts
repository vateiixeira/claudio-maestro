// Mirrors the backend contract (backend/vibing/api). Timestamps are Unix seconds.

export interface Project {
  id: number
  name: string
  path: string
  color: string
  position: number
  created_at: number
  available: boolean
}

export interface ProjectCreate {
  name: string
  path: string
  color: string
}

export interface ProjectUpdate {
  name?: string
  color?: string
  position?: number
}

export interface DirEntry {
  name: string
  path: string
  git: boolean
}

export interface DirListing {
  path: string
  parent: string | null
  entries: DirEntry[]
}

export type SessionState =
  | 'closed'
  | 'connecting'
  | 'running'
  | 'awaiting_decision'
  | 'idle'
  | 'error'

export interface Session {
  session_id: string
  project_id: number
  cwd: string
  title: string
  created_at: number
  last_activity_at: number
  state: SessionState
  error: string | null
  last_seen_at: number | null
  finished: boolean
  seq: number
  display_state: DisplayState
  unread: boolean
  awaiting_decision: boolean
}

/** What the user sees: running, waiting for them, or marked as finished. */
export type DisplayState = 'running' | 'waiting' | 'finished'

export interface SessionUpdate {
  finished?: boolean
  title?: string
}
