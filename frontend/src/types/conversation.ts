import type { DisplayState, Effort, PermissionMode, SessionState } from './api'

// Conversation items as the backend sends them (snapshot `items` and `item.upsert`).

/** Image or document the user attached, without its data. */
export interface Attachment {
  type: 'image' | 'document'
  media_type: string | null
  size: number | null
}

export interface UserItem {
  type: 'user'
  id: string
  text: string
  images?: Attachment[]
}

export interface TextItem {
  type: 'text' | 'thinking'
  id: string
  text: string
  streaming: boolean
  parent_tool_use_id: string | null
}

export interface ToolResult {
  content: unknown
  is_error: boolean
  details: Record<string, unknown> | null
}

export interface ToolItem {
  type: 'tool'
  id: string
  tool_use_id: string
  name: string
  input: Record<string, unknown>
  result: ToolResult | null
  streaming: boolean
  parent_tool_use_id: string | null
  /** Old session whose transcript has no result for this call. */
  result_missing?: boolean
  /** Present on `Agent`/`Task` calls. */
  subagent?: Subagent | null
}

export type SubagentStatus = 'running' | 'completed' | 'failed' | 'stopped'

export interface Subagent {
  task_id: string | null
  subagent_type: string | null
  description: string | null
  status: SubagentStatus
  last_activity: string | null
  usage: { total_tokens?: number | null; tool_uses?: number | null; duration_ms?: number | null } | null
  summary: string | null
}

export interface NoticeItem {
  type: 'notice'
  id: string
  level: 'info' | 'warning' | 'error'
  text: string
}

export type ConversationItem = UserItem | TextItem | ToolItem | NoticeItem

export interface QuestionOption {
  label: string
  description?: string | null
}

export interface Question {
  question: string
  header?: string | null
  options: QuestionOption[]
  multiSelect?: boolean
}

export interface PermissionPrompt {
  kind?: 'tool' | 'question' | 'plan'
  questions?: Question[]
  plan?: string
  prompt_id: string
  tool_name: string
  input: Record<string, unknown>
  display_name?: string | null
  description?: string | null
  title?: string | null
  tool_use_id?: string | null
  suggestions?: unknown[] | null
  can_always: boolean
}

export interface SessionInit {
  session_id: string
  model: string | null
  permission_mode: string | null
}

export interface TurnResult {
  subtype: string
  is_error: boolean
  duration_ms: number | null
  total_cost_usd: number | null
  usage?: unknown
  errors?: unknown
}

export interface SessionSnapshot {
  session_id: string
  project_id: number
  title: string
  cwd: string
  state: SessionState
  error: string | null
  seq: number
  items: ConversationItem[]
  prompts: PermissionPrompt[]
  init: SessionInit | null
  last_seen_at?: number | null
  finished?: boolean
  display_state?: DisplayState
  unread?: boolean
  awaiting_decision?: boolean
  history_truncated?: boolean
  external_activity?: boolean
  model?: string | null
  model_resolved?: string | null
  effort?: Effort | null
  permission_mode?: PermissionMode | null
  effort_pending?: boolean
}

export type PromptDecision = 'allow_once' | 'allow_always' | 'deny' | 'answer' | 'approve' | 'reject'

export interface PromptExtra {
  answers?: Record<string, string | string[]>
  message?: string
}
