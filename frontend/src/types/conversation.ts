import type { NoteCode } from '../conversation/terminalText'
import type { ContextUsage, DisplayState, Effort, PermissionMode, RemoteControlState, SessionState } from './api'

// Conversation items as the backend sends them (snapshot `items` and `item.upsert`).

/** Image or document the user attached, without its data. */
export interface Attachment {
  type: 'image' | 'document'
  media_type: string | null
  size: number | null
}

/** A command the user ran in the session's terminal and sent to Claude. */
export interface TerminalRun {
  command: string
  output: string
  /** Null when the command had not finished (the user typed into it, or the shell exited). */
  exit_code: number | null
  duration_ms: number | null
  /** Why the output is not the whole output of the command. */
  notes: NoteCode[]
}

export interface UserItem {
  type: 'user'
  id: string
  text: string
  images?: Attachment[]
  /** A message that came from the terminal: shown as a command box, `text` is empty. */
  terminal_run?: TerminalRun | null
  /** Pieces of terminal output attached to the message, in the order they were attached. */
  terminal_snippets?: string[]
  /** Sent live from the Claude app (Remote Control), not typed here. */
  remote?: boolean
  /** When the item was created (Unix seconds); absent or null when the history does not say. Same on every item type. */
  at?: number | null
}

export interface TextItem {
  type: 'text' | 'thinking'
  id: string
  text: string
  streaming: boolean
  parent_tool_use_id: string | null
  at?: number | null
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
  /** Present on `Bash` calls the CLI started in the background; absent in history. */
  background?: BackgroundTask | null
  at?: number | null
}

export interface BackgroundTask {
  task_id: string
  status: SubagentStatus
  summary: string | null
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
  /** When the subagent started and when it was last active (Unix seconds); null when the history does not say. */
  started_at?: number | null
  last_activity_at?: number | null
  /** The model it runs on (an id like "claude-sonnet-5-5", or the alias the call asked for); null until known. */
  model?: string | null
}

export interface NoticeItem {
  type: 'notice'
  id: string
  level: 'info' | 'warning' | 'error'
  text: string
  at?: number | null
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
  last_activity_at?: number
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
  remote_control?: boolean
  remote_control_state?: RemoteControlState
  remote_control_url?: string | null
  remote_control_error?: string | null
  context?: ContextUsage | null
  /** Output tokens the main agent generated in the running turn; 0 when none or unknown. */
  turn_output_tokens?: number
  /** When the open turn began (Unix seconds); null/absent while no turn is open. */
  turn_started_at?: number | null
}

export type PromptDecision = 'allow_once' | 'allow_always' | 'deny' | 'answer' | 'approve' | 'reject'

export interface PromptExtra {
  answers?: Record<string, string | string[]>
  message?: string
}
