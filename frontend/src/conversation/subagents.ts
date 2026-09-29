import type { InjectionKey, Ref } from 'vue'
import type { ConversationItem, SubagentStatus, ToolItem } from '../types/conversation'
import { AGENT_TOOLS } from './turns'
import { str, toolLabel } from './tool'

/** Where the user asked to go from the subagent strip: the card and the cards to open on the way. */
export interface SubagentFocus {
  id: string
  path: string[]
}
export const SUBAGENT_FOCUS_KEY: InjectionKey<Ref<SubagentFocus | null>> = Symbol('subagentFocus')

export interface SubagentEntry {
  /** Id of the conversation item (the card). */
  id: string
  kind: string
  description: string
  status: SubagentStatus
  lastAction: string
}

/** State of a subagent card: the SDK's when known, else inferred from the tool call. */
export function agentStatus(item: ToolItem, sessionActive: boolean): SubagentStatus {
  if (item.subagent) return item.subagent.status
  if (item.result?.is_error) return 'failed'
  if (item.result || item.result_missing || !sessionActive) return 'completed'
  return 'running'
}

const MAX_TARGET = 60

function clip(text: string): string {
  const line = text.split('\n', 1)[0]!.trim()
  return line.length > MAX_TARGET ? `${line.slice(0, MAX_TARGET - 1)}…` : line
}

function target(input: Record<string, unknown>): string {
  const path = str(input.file_path) || str(input.notebook_path)
  if (path) return path.split('/').filter(Boolean).pop() ?? path
  return clip(str(input.command) || str(input.pattern) || str(input.query) || str(input.url) || str(input.description))
}

function describeAction(item: ToolItem): string {
  return [toolLabel(item.name), target(item.input ?? {})].filter(Boolean).join(' ')
}

/**
 * The subagents of the current set: those of the turn in progress (after the last user
 * message) plus any earlier one still running, such as a background subagent.
 */
export function deriveSubagents(items: ConversationItem[], sessionActive: boolean): SubagentEntry[] {
  let turnStart = 0
  items.forEach((item, index) => { if (item.type === 'user') turnStart = index })

  const children = new Map<string, ToolItem[]>()
  for (const item of items) {
    if (item.type === 'tool' && item.parent_tool_use_id) {
      const list = children.get(item.parent_tool_use_id) ?? []
      list.push(item)
      children.set(item.parent_tool_use_id, list)
    }
  }
  // The latest action anywhere inside the card, nested subagents included.
  const order = new Map(items.map((item, index) => [item.id, index]))
  const latest = (toolUseId: string, seen = new Set<string>()): ToolItem | null => {
    if (seen.has(toolUseId)) return null
    seen.add(toolUseId)
    let best: ToolItem | null = null
    for (const child of children.get(toolUseId) ?? []) {
      for (const candidate of [child, latest(child.tool_use_id, seen)]) {
        if (candidate && (!best || order.get(candidate.id)! > order.get(best.id)!)) best = candidate
      }
    }
    return best
  }

  const entries: SubagentEntry[] = []
  items.forEach((item, index) => {
    if (item.type !== 'tool' || !AGENT_TOOLS.has(item.name)) return
    const status = agentStatus(item, sessionActive)
    if (index < turnStart && status !== 'running') return
    const action = latest(item.tool_use_id)
    entries.push({
      id: item.id,
      kind: item.subagent?.subagent_type || str(item.input.subagent_type),
      description: item.subagent?.description || str(item.input.description),
      status,
      lastAction: action ? describeAction(action) : item.subagent?.last_activity ?? '',
    })
  })
  return entries
}

/** What the strip shows: the whole set while any subagent runs, nothing otherwise. */
export function stripSubagents(entries: SubagentEntry[]): SubagentEntry[] {
  return entries.some((entry) => entry.status === 'running') ? entries : []
}

const COUNT_WORDS: Record<SubagentStatus, [string, string]> = {
  running: ['rodando', 'rodando'],
  completed: ['concluído', 'concluídos'],
  failed: ['com erro', 'com erro'],
  stopped: ['parado', 'parados'],
}

/** "3 rodando, 1 concluído": counts by state, in a fixed order. */
export function summarizeSubagents(entries: SubagentEntry[]): string {
  return (['running', 'completed', 'failed', 'stopped'] as const)
    .map((status) => [status, entries.filter((e) => e.status === status).length] as const)
    .filter(([, count]) => count > 0)
    .map(([status, count]) => `${count} ${COUNT_WORDS[status][count === 1 ? 0 : 1]}`)
    .join(', ')
}
