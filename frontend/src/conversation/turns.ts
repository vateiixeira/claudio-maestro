import type { ConversationItem, ToolItem, UserItem } from '../types/conversation'
import { TASK_TOOLS } from './tasks'

export const EDIT_TOOLS = new Set(['Edit', 'Write', 'MultiEdit'])
export const SEARCH_TOOLS = new Set(['Grep', 'Glob', 'WebSearch', 'WebFetch'])
export const AGENT_TOOLS = new Set(['Agent', 'Task'])

/**
 * One row of the assistant's rail. Only single items today; a future `group`
 * variant (consecutive actions) slots in here without changing `Turn`.
 */
export type TurnEntry = { kind: 'item'; item: ConversationItem }

export interface Turn {
  /** 1-based position in the conversation. */
  number: number
  /** The message that opened the turn; null for items before the first message. */
  user: UserItem | null
  entries: TurnEntry[]
}

/** Splits the top-level items into turns, each opened by a user message. */
export function buildTurns(items: ConversationItem[]): Turn[] {
  const turns: Turn[] = []
  let current: Turn | null = null
  for (const item of items) {
    if (item.type === 'user') {
      current = { number: turns.length + 1, user: item, entries: [] }
      turns.push(current)
      continue
    }
    if (!current) {
      current = { number: 1, user: null, entries: [] }
      turns.push(current)
    }
    current.entries.push({ kind: 'item', item })
  }
  return turns
}

export interface TurnSummary {
  /** Tool calls in the turn, including those inside subagents. */
  actions: number
  /** Distinct `file_path` of edit tools. */
  files: number
}

export function turnSummary(turn: Turn, childrenOf: (toolUseId: string) => ConversationItem[]): TurnSummary {
  let actions = 0
  const files = new Set<string>()
  const visit = (item: ConversationItem) => {
    if (item.type !== 'tool') return
    actions++
    const path = item.input.file_path
    if (EDIT_TOOLS.has(item.name) && typeof path === 'string' && path) files.add(path)
    childrenOf(item.tool_use_id).forEach(visit)
  }
  turn.entries.forEach((e) => visit(e.item))
  return { actions, files: files.size }
}

export type NodeKind =
  | 'text' | 'thinking' | 'read' | 'search' | 'bash' | 'edit' | 'task' | 'tool' | 'agent'
  | 'running' | 'error' | 'warning' | 'info'

function toolRunning(item: ToolItem, sessionActive: boolean): boolean {
  if (item.subagent) return item.subagent.status === 'running'
  return item.streaming || (!item.result && !item.result_missing && sessionActive)
}

/** Which rail node an item gets. */
export function nodeKind(item: ConversationItem, sessionActive: boolean): NodeKind {
  switch (item.type) {
    case 'text':
      return 'text'
    case 'thinking':
      return 'thinking'
    case 'notice':
      return item.level
    case 'user':
      return 'text'
  }
  if (item.result?.is_error || item.subagent?.status === 'failed') return 'error'
  if (toolRunning(item, sessionActive)) return 'running'
  if (AGENT_TOOLS.has(item.name)) return 'agent'
  if (item.name === 'Read') return 'read'
  if (SEARCH_TOOLS.has(item.name)) return 'search'
  if (item.name === 'Bash') return 'bash'
  if (EDIT_TOOLS.has(item.name)) return 'edit'
  if (TASK_TOOLS.has(item.name)) return 'task'
  return 'tool'
}

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`

/** "3 ações · 1 arquivo alterado" (files omitted when zero). */
export function summaryText(summary: TurnSummary): string {
  const parts = [plural(summary.actions, 'ação', 'ações')]
  if (summary.files) parts.push(plural(summary.files, 'arquivo alterado', 'arquivos alterados'))
  return parts.join(' · ')
}
