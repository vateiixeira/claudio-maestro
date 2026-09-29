import { vi } from 'vitest'
import type { Project, Session } from '../types/api'

export function makeProject(overrides: Partial<Project> = {}): Project {
  return {
    id: 1,
    name: 'loja-online',
    path: '/home/vi/dev/loja-online',
    color: '#B28CFF',
    position: 0,
    created_at: 1_790_000_000,
    available: true,
    hidden_sessions: 0,
    ...overrides,
  }
}

export function makeSession(overrides: Partial<Session> = {}): Session {
  return {
    session_id: 's1',
    project_id: 1,
    cwd: '/home/vi/dev/loja-online',
    title: 'Nova sessão',
    created_at: 1_790_000_000,
    last_activity_at: 1_790_000_000,
    state: 'closed',
    error: null,
    last_seen_at: null,
    finished: false,
    seq: 0,
    display_state: 'waiting',
    unread: false,
    awaiting_decision: false,
    ...overrides,
  }
}

type Handler = (init: RequestInit | undefined) => Response | Promise<Response>

/**
 * Stubs `fetch` with handlers keyed by "METHOD url" (e.g. "GET /api/projects").
 * Unknown requests fail the test with a 599 so they are easy to spot.
 */
export function routeFetch(handlers: Record<string, Handler>) {
  return vi.fn(async (url: string, init?: RequestInit) => {
    const key = `${init?.method ?? 'GET'} ${url}`
    const handler = handlers[key]
    if (!handler) return jsonResponse({ detail: `Sem resposta falsa para ${key}` }, 599)
    return handler(init)
  })
}

export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

export function makeSnapshot(overrides: Partial<import('../types/conversation').SessionSnapshot> = {}) {
  return {
    session_id: 's1',
    project_id: 1,
    title: 'Nova sessão',
    cwd: '/home/vi/dev/loja-online',
    state: 'idle' as const,
    error: null,
    seq: 0,
    items: [],
    prompts: [],
    init: null,
    ...overrides,
  }
}

export function makeEvent(type: string, data: unknown, seq: number, session_id = 's1') {
  return { session_id, seq, type, data }
}

export function makeGitRepo(overrides: Partial<import('../types/api').GitRepo> = {}): import('../types/api').GitRepo {
  return {
    path: '/home/vi/dev/loja-online',
    rel_path: '.',
    branch: 'main',
    detached: false,
    head: 'abc1234',
    changed: { staged: 0, unstaged: 0, untracked: 0 },
    error: null,
    ...overrides,
  }
}
