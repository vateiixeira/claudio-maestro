// Mirrors the backend contract (backend/vibing/api). Timestamps are Unix seconds.

export interface Project {
  id: number
  name: string
  path: string
  color: string
  position: number
  created_at: number
  available: boolean
  /** Sessions stopped for more than 3 days, left out of the menu. */
  hidden_sessions: number
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
  /** Branch name, short hash with a detached HEAD, or null. */
  branch?: string | null
  /** True when HEAD is detached; `branch` then holds the short hash. */
  detached?: boolean
}

/** A repository found under a folder (`GET /api/fs/repos`), same discovery as a project. */
export interface FoundRepo {
  name: string
  /** Relative to the folder; "." when the folder itself is the repository. */
  rel_path: string
  path: string
  branch: string | null
  detached: boolean
}

export interface FoundRepos {
  repos: FoundRepo[]
  /** More repositories than the limit (50); only the first ones are tracked. */
  limit_reached: boolean
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
  summary?: string | null
  first_prompt?: string | null
  model?: string | null
  model_resolved?: string | null
  effort?: Effort | null
  permission_mode?: PermissionMode | null
  effort_pending?: boolean
  /** Context window use, updated at the end of each turn. */
  context?: ContextUsage | null
  /** Oldest tool permission request waiting (questions and plans are null). */
  pending_permission?: PendingPermission | null
  /** When the user finished the session (seconds); null when open or finished by inactivity. */
  finished_at?: number | null
  /** Last tool of the main conversation ("Edit sessions.py"); null after a backend restart. */
  last_action?: string | null
  /** Kind of the oldest pending prompt. */
  pending_kind?: 'tool' | 'question' | 'plan' | null
  /** Progress of the plan file linked to the session; null when there is none. */
  plan?: PlanSummary | null
  /** True when the app has no client for the conversation but the CLI is mid-turn (subagents included). */
  cli_running?: boolean
}

export interface PlanCurrent { number: number; title: string }
export interface PlanSummary { path: string; title: string; total: number; done: number; current: PlanCurrent | null }
export interface PlanTask { number: number; title: string; done: boolean }
export interface PlanState { link: 'auto' | 'manual' | 'off'; path: string | null; plan: PlanSummary | null; tasks: PlanTask[] }
export interface ProjectPlan { path: string; title: string; total: number; done: number }

/** Conversations with messages on a day, per project (`GET /api/activity`). */
export interface ActivityDay {
  date: string
  project_id: number
  sessions: number
}

export interface ContextUsage {
  used_tokens: number
  max_tokens: number
  percent: number
}

export interface PendingPermission {
  prompt_id: string
  tool_name: string
  summary: string
  can_allow_always: boolean
}

/** What the user sees: running, waiting for them, or marked as finished. */
export type DisplayState = 'running' | 'waiting' | 'finished'

export interface SendResult {
  state: SessionState
  external_activity: boolean
}

export type Effort = 'low' | 'medium' | 'high' | 'xhigh' | 'max'
export type PermissionMode = 'default' | 'acceptEdits' | 'plan' | 'bypassPermissions' | 'auto' | 'dontAsk'

/** Model, reasoning and permission mode of a session (`session.options`). */
export interface SessionOptions {
  /** Alias chosen by the user, or null for the account default. */
  model: string | null
  /** Model id actually in use; only for display. */
  model_resolved: string | null
  effort: Effort | null
  permission_mode: PermissionMode | null
  /** The new effort applies from the next turn. */
  effort_pending: boolean
}

export interface ModelInfo {
  value: string
  displayName: string
  description: string
  supportsEffort?: boolean
  supportedEffortLevels?: Effort[]
}

export interface SessionUpdate {
  finished?: boolean
  title?: string
  model?: string
  effort?: Effort
  permission_mode?: PermissionMode
  confirm_bypass?: boolean
}

/** Image sent with a message: base64 without the `data:` prefix. */
export interface ImageInput {
  media_type: string
  data: string
}

export interface GitRepo {
  path: string
  /** Relative to the project folder; "." when the folder itself is the repository. */
  rel_path: string
  branch: string | null
  detached: boolean
  head: string | null
  changed: { staged: number; unstaged: number; untracked: number }
  error: string | null
}

export interface ChangedFile {
  path: string
  rel_path: string
  added: number | null
  removed: number | null
  uncommitted: boolean
}

/** Files changed in a session, per repository. The group without a repository has nulls. */
export interface ChangesGroup {
  path: string | null
  rel_path: string | null
  branch: string | null
  detached: boolean
  head: string | null
  files: ChangedFile[]
}

export interface FileDiff {
  diff: string
  truncated: boolean
  notice?: string | null
}
