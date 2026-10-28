// Organization of agents: the shapes of `backend/claudio_maestro/api/org.py` and of the dataclasses of
// `backend/claudio_maestro/org/store.py` that it returns as they are.

import type { Effort } from './api'

export type RunOutcome =
  | 'starting'
  | 'running'
  | 'waiting'
  | 'concluded'
  | 'closed'
  | 'failed'
  | 'skipped'
  | 'missed'
  | 'cancelled'

/** What woke the agent up. */
export type WakeSource = 'routine' | 'message' | 'assignment' | 'comment' | 'decision' | 'manual'

export type TaskStatus = 'todo' | 'in_progress' | 'in_review' | 'blocked' | 'done' | 'cancelled'
export type TaskPriority = 'urgent' | 'high' | 'normal' | 'low'
export type CommentAuthor = 'human' | 'agent' | 'app'
export type TaskCreator = 'human' | 'agent' | 'routine'
export type DecisionStatus = 'pending' | 'answered' | 'expired'
export type NoticeKind = 'notice' | 'summary' | 'alert'

export interface Run {
  id: number
  agent_id: number
  session_id: string | null
  source: WakeSource
  routine_id: number | null
  scheduled_for: number | null
  started_at: number
  ended_at: number | null
  outcome: RunOutcome
  reason: string | null
  task_id: number | null
  /** The run left a comment on its task. */
  commented: boolean
  /** The run was woken once more because it ended without commenting. */
  rewoken: boolean
}

/** What `GET /api/agents` returns for each agent. */
export interface Agent {
  id: number
  slug: string
  name: string
  /** The `description` of the AGENT.md; empty when the file does not open. */
  description: string
  project_id: number
  /** The boss; null for a top agent. */
  reports_to: number | null
  enabled: boolean
  model: string | null
  effort: Effort | null
  /** Why the AGENT.md does not open (missing or invalid); null when it is fine. */
  definition_error: string | null
  /** The agent holds a run or has a turn open. */
  busy: boolean
  /** The permanent main conversation; null until it is first opened. */
  main_session_id: string | null
  /** Announcements the main conversation has not received yet, plus one while it waits for an answer. */
  unseen: number
  last_run: Run | null
}

export interface AgentCreate {
  name: string
  slug: string
  project_id: number
  reports_to?: number | null
  kind?: 'cto' | 'worker' | 'reviewer'
}

/** The name comes from the AGENT.md, so it is not editable here; `reports_to: null` makes a top agent. */
export interface AgentUpdate {
  name?: string
  reports_to?: number | null
  enabled?: boolean
}

export interface AgentDefinitionFile {
  text: string
  hash: string
}

/** A queued wakeup (`GET /api/agents/{id}/wakeups`), with a preview of its text. */
export interface Wakeup {
  id: number
  agent_id: number
  source: WakeSource
  priority: number
  routine_id: number | null
  payload: Record<string, unknown> | null
  state: 'pending' | 'taken' | 'dropped'
  run_id: number | null
  created_at: number
  taken_at: number | null
  task_id: number | null
  text: string
}

export interface Notice {
  id: number
  agent_id: number
  run_id: number | null
  kind: NoticeKind
  text: string
  created_at: number
  read_at: number | null
}

/** What a run announced to the agent's main conversation. */
export interface Announcement {
  id: number
  /** Absent in the list of an agent; present in the `agent.announcement` event. */
  agent_id?: number
  run_id: number | null
  session_id: string | null
  text: string
  created_at: number
  /** Null while the main conversation has not received it. */
  delivered_at: number | null
}

export interface Conversation {
  session_id: string
  title: string
  finished: boolean
  created_at: number
  last_activity_at: number
}

/** A pending message of a conversation, waiting for a run to end. */
export interface PendingMessage {
  id: number
  text: string
}

/** One entry of the agent's registry (what it keeps track of between runs). */
export interface RegistryItem {
  key: string
  status: string
  link: string | null
  note: string | null
  created_at: number
  updated_at: number
}

export interface Schedule {
  id: number
  /** ISO weekday digits, "1" = Monday ... "7" = Sunday. */
  days: string
  /** "HH:MM", local time. */
  time: string
  last_fired_at: number | null
}

export interface Routine {
  id: number
  project_id: number
  agent_id: number
  name: string
  instruction: string
  enabled: boolean
  /** Each firing opens a task for the agent instead of a bare run. */
  create_task: boolean
  created_at: number
  updated_at: number
  schedules: Schedule[]
}

export interface RoutineCreate {
  agent_id: number
  name: string
  instruction: string
  project_id?: number
  enabled?: boolean
  create_task?: boolean
  schedules?: { days: string; time: string }[]
}

export interface RoutineUpdate {
  name?: string
  instruction?: string
  enabled?: boolean
  create_task?: boolean
  schedules?: { days: string; time: string }[]
}

export interface Task {
  id: number
  project_id: number
  parent_task_id: number | null
  title: string
  description: string
  status: TaskStatus
  priority: TaskPriority
  assignee_agent_id: number | null
  reviewer_agent_id: number | null
  created_by_agent_id: number | null
  created_by: TaskCreator
  routine_id: number | null
  /** Bumped by every change; a stale one is refused with 409. */
  revision: number
  run_count: number
  max_runs: number
  worktree_path: string | null
  branch: string | null
  blocked_reason: string | null
  legacy: Record<string, unknown> | null
  created_at: number
  updated_at: number
  closed_at: number | null
}

export interface TaskCreate {
  project_id: number
  title: string
  description?: string
  assignee_agent_id?: number | null
  reviewer_agent_id?: number | null
  parent_task_id?: number | null
  priority?: TaskPriority
}

/** Only the keys present are changed: `assignee_agent_id: null` clears the assignee, leaving the key out keeps it. */
export interface TaskUpdate {
  expected_revision: number
  status?: TaskStatus
  assignee_agent_id?: number | null
  reviewer_agent_id?: number | null
  priority?: TaskPriority
  title?: string
  description?: string
  max_runs?: number
  comment?: string
}

export interface TaskFilter {
  project_id?: number
  status?: TaskStatus | TaskStatus[]
  assignee_agent_id?: number
  limit?: number
  offset?: number
  /** `id` (default): oldest first. `recent`: the latest change first. */
  order?: 'id' | 'recent'
}

export interface Comment {
  id: number
  task_id: number
  author_kind: CommentAuthor
  author_agent_id: number | null
  run_id: number | null
  text: string
  created_at: number
}

export interface Decision {
  id: number
  project_id: number
  task_id: number | null
  agent_id: number
  run_id: number | null
  /** The session that asked. */
  session_id: string | null
  question: string
  options: string[]
  answer: string | null
  receipt: string | null
  status: DecisionStatus
  created_at: number
  answered_at: number | null
}

export interface TaskPr {
  url: string
  agent_id: number
  session_id: string | null
  created_at: number
  polled_at: number | null
  closed: boolean
  task_id: number | null
}

export interface CiReceipt {
  id: number
  project_id: number
  task_id: number | null
  agent_id: number | null
  run_id: number | null
  run_url: string | null
  repository: string | null
  head_sha: string | null
  conclusion: string | null
  jobs: unknown
  receipt: string | null
  created_at: number
}

/** `GET /api/tasks/{id}`. */
export interface TaskDetail {
  task: Task
  comments: Comment[]
  runs: Run[]
  decisions: Decision[]
  prs: TaskPr[]
  ci: CiReceipt[]
}

/** `GET /api/agents-github`: the owner whose PR comments are accepted and the webhook state. The secret is only written. */
export interface GithubSettings {
  login: string | null
  secret_set: boolean
  hooks_port: number | null
  /** PR comments waiting to be handled. */
  queued: number
}

/** The `task` event: what changed in a task. */
export interface TaskEvent {
  id: number
  project_id: number
  status: TaskStatus
  revision: number
  change: string
}

/** The 422 of `PUT /api/agents/{id}/definition`. */
export interface DefinitionErrorBody {
  detail: string
  field: string | null
  line: number | null
}
