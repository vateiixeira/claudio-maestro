import { vi } from 'vitest'
import type { Label, Project, Session, SessionGroup } from '../types/api'

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

export function makeGroup(overrides: Partial<SessionGroup> = {}): SessionGroup {
  return { id: 1, project_id: 1, name: 'Checkout', created_at: 1_790_000_000, ...overrides }
}

export function makeLabel(overrides: Partial<Label> = {}): Label {
  return { id: 1, slug: 'urgente', color: '#ef4444', created_at: 1_790_000_000, ...overrides }
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
    upstream: 'origin/main',
    ahead: 0,
    behind: 0,
    error: null,
    ...overrides,
  }
}

export function makeRepoDetails(
  overrides: Partial<import('../types/api').RepoDetails> = {},
): import('../types/api').RepoDetails {
  return {
    ...makeGitRepo(), files: [], files_truncated: false, commits: [],
    head_sha: 'abc1234abc1234abc1234abc1234abc1234abc12', state: makeRepoState(),
    ...overrides,
  }
}

export function makeRepoCommit(
  overrides: Partial<import('../types/api').RepoCommit> = {},
): import('../types/api').RepoCommit {
  return {
    hash: 'abc1234',
    full_hash: 'abc1234abc1234abc1234abc1234abc1234abc12',
    subject: 'Ajustar o carrinho',
    author: 'Fulano',
    date: '2026-09-30T12:00:00-03:00',
    pushed: true,
    ...overrides,
  }
}

export function makeRepoState(overrides: Partial<import('../types/api').RepoState> = {}): import('../types/api').RepoState {
  return {
    merging: false, merge_head: null, merge_branch: null, merge_message: null, conflicts: [],
    has_hooks: false, read_only: null, no_merge: null, gpgsign: false,
    user_email: 'eu@example.com', remotes: ['origin'],
    ...overrides,
  }
}

export function makeLogCommit(overrides: Partial<import('../types/api').LogCommit> = {}): import('../types/api').LogCommit {
  const full = overrides.full_hash ?? 'abc1234abc1234abc1234abc1234abc1234abc12'
  return {
    hash: full.slice(0, 7), full_hash: full, parents: ['0000000000000000000000000000000000000000'],
    subject: 'Ajustar o carrinho', body: '', author: 'Fulano', email: 'fulano@example.com',
    date: '2026-09-30T12:00:00-03:00', pushed: true,
    ...overrides,
  }
}

export function makeRepoLog(overrides: Partial<import('../types/api').RepoLog> = {}): import('../types/api').RepoLog {
  return {
    ref: 'refs/heads/main', branch: 'main', upstream: 'origin/main', upstream_sha: null,
    commits: [], has_more: false, incoming: [], incoming_count: 0, outgoing_count: 0,
    ...overrides,
  }
}

export function makeBranchList(overrides: Partial<import('../types/api').BranchList> = {}): import('../types/api').BranchList {
  return {
    current: 'refs/heads/main',
    local: [
      { name: 'main', ref: 'refs/heads/main', sha: 'abc1234', date: '2026-09-30T12:00:00-03:00', upstream: 'origin/main' },
      { name: 'feat/relatorios', ref: 'refs/heads/feat/relatorios', sha: 'def5678', date: '2026-09-29T12:00:00-03:00', upstream: null },
    ],
    remote: [
      { name: 'origin/main', ref: 'refs/remotes/origin/main', sha: 'abc1234', date: '2026-09-30T12:00:00-03:00', upstream: null },
    ],
    ...overrides,
  }
}

/** Key of `routeFetch` for GET /git/log, in the order `getRepoLog` builds the query. */
export function logUrl(projectId: number, repo: string, skip = 0, ref: string | null = null, limit?: number): string {
  const query = new URLSearchParams({ repo, skip: String(skip) })
  if (ref) query.set('ref', ref)
  if (limit !== undefined) query.set('limit', String(limit))
  return `GET /api/projects/${projectId}/git/log?${query}`
}

export function makeSpecialist(overrides: Partial<import('../types/api').Specialist> = {}): import('../types/api').Specialist {
  return {
    id: 1,
    slug: 'sentry',
    name: 'Sentry',
    description: 'Trata os erros novos do Sentry',
    project_id: 1,
    extra_project_ids: [],
    autonomy: 'ask',
    outward_patterns: [],
    always_ask_patterns: [],
    denied_tools: [],
    close_by_check: false,
    model: null,
    effort: null,
    run_text: 'Siga a skill.',
    enabled: true,
    last_mcp: [],
    schedules: [],
    queue_paused: false,
    last_run: null,
    open_sessions: 0,
    main_session_id: null,
    unseen: 0,
    ...overrides,
  }
}

export function makeSpecialistRun(overrides: Partial<import('../types/api').SpecialistRun> = {}): import('../types/api').SpecialistRun {
  return {
    id: 1,
    specialist_id: 1,
    session_id: 's1',
    trigger: 'manual',
    scheduled_for: null,
    started_at: 1_790_000_000,
    ended_at: null,
    outcome: 'running',
    reason: null,
    ...overrides,
  }
}

export function makeSpecialistNotice(overrides: Partial<import('../types/api').SpecialistNotice> = {}): import('../types/api').SpecialistNotice {
  return {
    id: 1,
    specialist_id: 1,
    session_id: 's1',
    kind: 'summary',
    text: 'Tratei 2 erros.',
    created_at: 1_790_000_000,
    read_at: null,
    ...overrides,
  }
}

export function makeRun(overrides: Partial<import('../types/org').Run> = {}): import('../types/org').Run {
  return {
    id: 1,
    agent_id: 1,
    session_id: 's1',
    source: 'manual',
    routine_id: null,
    scheduled_for: null,
    started_at: 1_790_000_000,
    ended_at: null,
    outcome: 'running',
    reason: null,
    task_id: null,
    commented: false,
    rewoken: false,
    ...overrides,
  }
}

export function makeAgent(overrides: Partial<import('../types/org').Agent> = {}): import('../types/org').Agent {
  return {
    id: 1,
    slug: 'cto',
    name: 'CTO',
    description: 'Coordena o time',
    project_id: 1,
    reports_to: null,
    enabled: true,
    model: null,
    effort: null,
    definition_error: null,
    busy: false,
    main_session_id: null,
    unseen: 0,
    last_run: null,
    ...overrides,
  }
}

export function makeNotice(overrides: Partial<import('../types/org').Notice> = {}): import('../types/org').Notice {
  return {
    id: 1,
    agent_id: 1,
    run_id: 1,
    kind: 'summary',
    text: 'Tratei 2 erros.',
    created_at: 1_790_000_000,
    read_at: null,
    ...overrides,
  }
}

export function makeTask(overrides: Partial<import('../types/org').Task> = {}): import('../types/org').Task {
  return {
    id: 1,
    project_id: 1,
    parent_task_id: null,
    title: 'Corrigir o carrinho',
    description: '',
    status: 'todo',
    priority: 'normal',
    assignee_agent_id: null,
    reviewer_agent_id: null,
    created_by_agent_id: null,
    created_by: 'human',
    routine_id: null,
    revision: 1,
    run_count: 0,
    max_runs: 20,
    worktree_path: null,
    branch: null,
    blocked_reason: null,
    legacy: null,
    created_at: 1_790_000_000,
    updated_at: 1_790_000_000,
    closed_at: null,
    ...overrides,
  }
}

export function makeComment(overrides: Partial<import('../types/org').Comment> = {}): import('../types/org').Comment {
  return {
    id: 1,
    task_id: 1,
    author_kind: 'human',
    author_agent_id: null,
    run_id: null,
    text: 'Pode seguir.',
    created_at: 1_790_000_000,
    ...overrides,
  }
}

export function makeRoutine(overrides: Partial<import('../types/org').Routine> = {}): import('../types/org').Routine {
  return {
    id: 1,
    project_id: 1,
    agent_id: 1,
    name: 'Triagem da manhã',
    instruction: 'Veja os erros novos.',
    enabled: true,
    create_task: false,
    created_at: 1_790_000_000,
    updated_at: 1_790_000_000,
    schedules: [],
    ...overrides,
  }
}

export function makeDecision(overrides: Partial<import('../types/org').Decision> = {}): import('../types/org').Decision {
  return {
    id: 1,
    project_id: 1,
    task_id: null,
    agent_id: 1,
    run_id: null,
    session_id: null,
    question: 'Posso publicar?',
    options: ['Sim', 'Não'],
    answer: null,
    receipt: null,
    status: 'pending',
    created_at: 1_790_000_000,
    answered_at: null,
    ...overrides,
  }
}

export function makeTaskDetail(overrides: Partial<import('../types/org').TaskDetail> = {}): import('../types/org').TaskDetail {
  return { task: makeTask(), comments: [], runs: [], decisions: [], prs: [], ci: [], ...overrides }
}
