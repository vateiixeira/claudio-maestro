import type { ConversationItem, ToolItem, UserItem } from '../types/conversation'
import { TASK_TOOLS } from './tasks'

export const EDIT_TOOLS = new Set(['Edit', 'Write', 'MultiEdit'])
export const SEARCH_TOOLS = new Set(['Grep', 'Glob', 'WebSearch', 'WebFetch'])
export const AGENT_TOOLS = new Set(['Agent', 'Task'])

/**
 * One row of the assistant's rail: a single item (text, thinking, notice, task list, question or
 * plan), or a group, the work block: everything Claude did between two statements. A group's id
 * is its first item's id, so it keeps its state while it grows.
 */
export type TurnEntry =
  | { kind: 'item'; item: ConversationItem }
  | { kind: 'group'; id: string; items: ToolItem[] }

/** Tools that ask the user something: they are shown by themselves, never inside a work block. */
const ASK_TOOLS = new Set(['AskUserQuestion', 'ExitPlanMode'])

/**
 * Work is any tool call (read, search, edit, command, other tool, subagent), failed or still
 * waiting for permission. Task lists, questions and plans are not: they stand on their own.
 */
function isWork(item: ConversationItem): item is ToolItem {
  return item.type === 'tool' && !TASK_TOOLS.has(item.name) && !ASK_TOOLS.has(item.name)
}

/**
 * Tidies the thinking in a list of items: a finished thought with no text is dropped,
 * and consecutive thoughts become one (texts joined by a blank line, the first one's id
 * so the block keeps its state, `streaming` of the last). Never mutates the input.
 */
export function tidyThinking(items: ConversationItem[]): ConversationItem[] {
  const out: ConversationItem[] = []
  for (const item of items) {
    if (item.type !== 'thinking') {
      out.push(item)
      continue
    }
    if (!item.streaming && !item.text.trim()) continue
    const prev = out[out.length - 1]
    if (prev?.type === 'thinking') {
      const text = [prev.text, item.text].filter((t) => t.trim()).join('\n\n')
      out[out.length - 1] = { ...prev, text, streaming: item.streaming }
    } else out.push(item)
  }
  return out
}

function groupEntries(items: ConversationItem[]): TurnEntry[] {
  items = tidyThinking(items)
  const entries: TurnEntry[] = []
  let run: ToolItem[] = []
  const flush = () => {
    if (run.length) entries.push({ kind: 'group', id: run[0]!.id, items: run })
    run = []
  }
  for (const item of items) {
    if (isWork(item)) {
      run.push(item)
      continue
    }
    flush()
    entries.push({ kind: 'item', item })
  }
  flush()
  return entries
}

export interface Turn {
  /** 1-based position in the conversation. */
  number: number
  /** The message that opened the turn; null for items before the first message. */
  user: UserItem | null
  entries: TurnEntry[]
}

/** Splits the top-level items into turns, each opened by a user message. */
export function buildTurns(items: ConversationItem[]): Turn[] {
  const turns: { number: number; user: UserItem | null; items: ConversationItem[] }[] = []
  let current: (typeof turns)[number] | null = null
  for (const item of items) {
    if (item.type === 'user') {
      current = { number: turns.length + 1, user: item, items: [] }
      turns.push(current)
      continue
    }
    if (!current) {
      current = { number: 1, user: null, items: [] }
      turns.push(current)
    }
    current.items.push(item)
  }
  return turns.map(({ number, user, items }) => ({ number, user, entries: groupEntries(items) }))
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
  turn.entries.forEach((e) => (e.kind === 'group' ? e.items.forEach(visit) : visit(e.item)))
  return { actions, files: files.size }
}

export type NodeKind =
  | 'text' | 'thinking' | 'read' | 'search' | 'bash' | 'edit' | 'task' | 'tool' | 'agent'
  | 'running' | 'error' | 'warning' | 'info' | 'group'

export function toolRunning(item: ToolItem, sessionActive: boolean): boolean {
  if (item.subagent) return item.subagent.status === 'running'
  // A background command ran at launch; what matters is the task, not the launch result.
  if (item.background) return item.background.status === 'running'
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
  if (item.result?.is_error || item.subagent?.status === 'failed' || item.background?.status === 'failed') return 'error'
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

/** A work block's node: running while any of its actions runs, else error if one failed. */
export function groupNodeKind(items: ToolItem[], sessionActive: boolean): NodeKind {
  if (items.some((item) => toolRunning(item, sessionActive))) return 'running'
  return items.some((item) => nodeKind(item, sessionActive) === 'error') ? 'error' : 'group'
}
