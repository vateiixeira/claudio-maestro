import type { ConversationItem, ToolItem, UserItem } from '../types/conversation'
import { TASK_TOOLS } from './tasks'
import { countLines, resultText, str, toolLabel } from './tool'

export const EDIT_TOOLS = new Set(['Edit', 'Write', 'MultiEdit'])
export const SEARCH_TOOLS = new Set(['Grep', 'Glob', 'WebSearch', 'WebFetch'])
export const AGENT_TOOLS = new Set(['Agent', 'Task'])

/**
 * One row of the assistant's rail: a single item, or a group of two or more
 * consecutive light actions. A group's id is its first item's id.
 */
export type TurnEntry =
  | { kind: 'item'; item: ConversationItem }
  | { kind: 'group'; id: string; items: ToolItem[] }

/** Reads, searches, commands and generic tools without error can join a group. */
function groupable(item: ConversationItem): item is ToolItem {
  if (item.type !== 'tool' || item.result?.is_error) return false
  return !EDIT_TOOLS.has(item.name) && !AGENT_TOOLS.has(item.name) && !TASK_TOOLS.has(item.name)
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
    if (run.length >= 2) entries.push({ kind: 'group', id: run[0]!.id, items: run })
    else run.forEach((item) => entries.push({ kind: 'item', item }))
    run = []
  }
  for (const item of items) {
    if (groupable(item)) {
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

function toolRunning(item: ToolItem, sessionActive: boolean): boolean {
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

/** A group's node: running while any of its actions runs. */
export function groupNodeKind(items: ToolItem[], sessionActive: boolean): NodeKind {
  return items.some((item) => toolRunning(item, sessionActive)) ? 'running' : 'group'
}

export type ActionCategory = 'read' | 'search' | 'bash' | 'tool'
function category(item: ToolItem): ActionCategory {
  if (item.name === 'Read') return 'read'
  if (SEARCH_TOOLS.has(item.name)) return 'search'
  if (item.name === 'Bash') return 'bash'
  return 'tool'
}
const CATEGORY_WORDS: Record<ActionCategory, [string, string, string]> = {
  read: ['Leitura', 'leitura', 'leituras'],
  search: ['Busca', 'busca', 'buscas'],
  bash: ['Comando', 'comando', 'comandos'],
  tool: ['Ferramenta', 'ferramenta', 'ferramentas'],
}

/** "2 leituras", "1 busca"… in a fixed order, only the kinds present. */
export function groupChips(items: ToolItem[]): string[] {
  const counts = new Map<ActionCategory, number>()
  items.forEach((item) => counts.set(category(item), (counts.get(category(item)) ?? 0) + 1))
  return (['read', 'search', 'bash', 'tool'] as const)
    .filter((c) => counts.has(c))
    .map((c) => plural(counts.get(c)!, CATEGORY_WORDS[c][1], CATEGORY_WORDS[c][2]))
}

export interface ActionRow {
  kind: ActionCategory
  label: string
  target: string
  meta: string
}

/** Compact line of one action inside a group. */
export function actionRow(item: ToolItem, sessionActive: boolean): ActionRow {
  const cat = category(item)
  const input = item.input ?? {}
  let target: string
  if (cat === 'read') target = str(input.file_path)
  else if (cat === 'search') {
    const subject = str(input.pattern) || str(input.query) || str(input.url)
    target = str(input.path) ? `${subject} em ${str(input.path)}` : subject
  } else if (cat === 'bash') target = str(input.command)
  else target = toolLabel(item.name)

  let meta = ''
  if (item.result_missing) meta = 'Resultado não disponível no histórico'
  else if (toolRunning(item, sessionActive)) meta = 'rodando…'
  else if (!item.result) meta = 'sem resultado'
  else if (cat === 'read') meta = plural(countLines(resultText(item.result.content)), 'linha', 'linhas')
  else if (item.name === 'Grep' || item.name === 'Glob') {
    meta = plural(countLines(resultText(item.result.content)), 'resultado', 'resultados')
  }
  return { kind: cat, label: CATEGORY_WORDS[cat][0], target, meta }
}
