import type { DisplayState, SessionState } from './api'

// Conversation items as the backend sends them (snapshot `items` and `item.upsert`).

export interface UserItem {
  type: 'user'
  id: string
  text: string
  images?: unknown[]
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
}

export interface NoticeItem {
  type: 'notice'
  id: string
  level: 'info' | 'warning' | 'error'
  text: string
}

export type ConversationItem = UserItem | TextItem | ToolItem | NoticeItem

export interface PermissionPrompt {
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
}

export type PromptDecision = 'allow_once' | 'allow_always' | 'deny'
