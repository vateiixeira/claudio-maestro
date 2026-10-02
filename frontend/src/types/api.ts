// Mirrors the backend contract (backend/claudio_maestro/api). Timestamps are Unix seconds.

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
  /** True when the app's client still runs a subagent or a Bash command (in the background) after the main turn ended. */
  subagents_running?: boolean
  /** Group of related sessions in the project; null (or absent) when loose. */
  group_id?: number | null
  /** Linked git worktree the session works in; null outside worktrees. */
  worktree_name?: string | null
  worktree_path?: string | null
  /** Newest git branch recorded in the session's transcript. */
  git_branch?: string | null
  /** Short sentence of the digest agent's summary; null before the first reading. */
  digest_short?: string | null
  /** The digest agent marked the linked plan as completed. */
  plan_done?: boolean
}

/** Group of related sessions inside a project (`GET /api/groups`). Only the app knows it. */
export interface SessionGroup {
  id: number
  project_id: number
  name: string
  created_at: number
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
  group_id?: number | null
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
  /** Tracked remote branch ("origin/main"); null when the branch has none. */
  upstream: string | null
  /** Commits not pushed yet; null without upstream or when the upstream is gone. */
  ahead: number | null
  /** Commits to pull (as of the last fetch); null without upstream or when it is gone. */
  behind: number | null
  error: string | null
}

export type RepoFileStatus = 'staged' | 'unstaged' | 'untracked'

/** Changed file of a repository; a file both staged and unstaged shows up twice. */
export interface RepoFile {
  /** Relative to the repository. */
  path: string
  status: RepoFileStatus
  /** Null for untracked and binary files. */
  added: number | null
  removed: number | null
}

export interface RepoCommit {
  hash: string
  full_hash: string
  subject: string
  author: string
  /** ISO 8601. */
  date: string
  /** Null when the branch has no upstream. */
  pushed: boolean | null
}

export interface RepoDetails extends GitRepo {
  files: RepoFile[]
  files_truncated: boolean
  commits: RepoCommit[]
}

export interface ProjectGitDetails {
  repos: RepoDetails[]
  limit_reached: boolean
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
  /** Name of the git worktree this group belongs to; absent or null for a regular repository. */
  worktree?: string | null
  files: ChangedFile[]
}

export interface FileDiff {
  diff: string
  truncated: boolean
  notice?: string | null
}

export type DigestPhaseKind = 'plan' | 'spec' | 'feature' | 'adjustments' | 'investigation' | 'other'
export interface DigestPhase {
  title: string
  kind: DigestPhaseKind
  status: 'open' | 'done'
  done: string[]
  pending: string[]
  ref: string | null
}
/** Summary kept by the digest agent (`GET /api/sessions/{id}/digest`). */
export interface SessionDigest {
  session_id: string
  read_at: number | null
  short: string | null
  phases: DigestPhase[]
  plan_done: boolean
  error: string | null
  error_at: number | null
}
export interface DigestConfig {
  enabled: boolean
  model: string
  effort: Effort
  extra_instructions: string
  interval_minutes: number
  min_new_messages: number
  open_turn_minutes: number
  window_days: number
}
export interface DigestStatus { enabled: boolean; running: boolean; next_run_at: number | null; paused_until: number | null }
export interface DigestState { config: DigestConfig; status: DigestStatus }
export interface DigestRunError { session_id: string; title: string; message: string }
export interface DigestRun {
  id: number
  started_at: number
  finished_at: number | null
  trigger: 'auto' | 'manual_all' | 'manual_session'
  read_count: number
  skipped_count: number
  errors: DigestRunError[]
  stopped: string | null
}

/** A slash command the agent offers (from the catalog endpoint). */
export interface CommandInfo { name: string; description: string; argument_hint: string }
/** A file or folder matched by the `@` mention search. */
export interface FileMatch { path: string; name: string; type: 'file' | 'directory' }
/** Where the suggestion endpoints read from: an existing session or a project folder. */
export type SuggestionScope = { sessionId: string } | { projectId: number }
