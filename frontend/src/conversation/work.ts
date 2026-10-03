import type { ToolItem } from '../types/conversation'
import { backgroundState } from './background'
import { diffCounts, toolDiff } from './diff'
import { agentStatus } from './subagents'
import { countLines, resultText, str, toolLabel } from './tool'
import { AGENT_TOOLS, EDIT_TOOLS, SEARCH_TOOLS, toolRunning, type NodeKind } from './turns'

// What a work block (the actions between two statements) says about each of its actions.

export type WorkKind = 'bash' | 'tool' | 'read' | 'search' | 'edit' | 'agent'
export type WorkStatus = 'ok' | 'running' | 'error' | 'stopped' | 'idle'

export const WORK_LABEL: Record<WorkKind, string> = {
  bash: 'Comando', tool: 'Ferramenta', read: 'Leitura', search: 'Busca', edit: 'Edição', agent: 'Subagente',
}

export function workKind(item: ToolItem): WorkKind {
  if (AGENT_TOOLS.has(item.name)) return 'agent'
  if (item.name === 'Read') return 'read'
  if (SEARCH_TOOLS.has(item.name)) return 'search'
  if (item.name === 'Bash') return 'bash'
  if (EDIT_TOOLS.has(item.name)) return 'edit'
  return 'tool'
}

export function workStatus(item: ToolItem, sessionActive: boolean): WorkStatus {
  if (AGENT_TOOLS.has(item.name)) {
    const status = agentStatus(item, sessionActive)
    return status === 'completed' ? 'ok' : status === 'failed' ? 'error' : status
  }
  if (item.result?.is_error || item.background?.status === 'failed') return 'error'
  if (toolRunning(item, sessionActive)) return 'running'
  const background = backgroundState(item)
  if (background === 'stopped') return 'stopped'
  if (background === 'completed' || background === 'unknown') return 'ok'
  if (item.result_missing || !item.result) return 'idle'
  return 'ok'
}

export interface WorkRow {
  kind: WorkKind
  /** Replaces the default label of the kind ("Escrita" for a Write). */
  label?: string
  /** Chip before the description: the search tool, the subagent type. */
  tag?: string
  desc: string
  /** The description is a path or a command: monospaced. */
  mono: boolean
  status: WorkStatus
  meta?: string
  /** First line of a command that has a description, shown on a second line while the row is closed. */
  command?: string
  /** Lines added and removed by an edit. */
  diff?: { added: number; removed: number }
}

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`

/** The compact line of one action in a work block. */
export function workRow(item: ToolItem, sessionActive: boolean): WorkRow {
  const kind = workKind(item)
  const status = workStatus(item, sessionActive)
  const input = item.input ?? {}
  const row: WorkRow = { kind, desc: '', mono: true, status }
  let meta: string | undefined
  if (kind === 'read') {
    row.desc = str(input.file_path)
    if (status === 'ok') meta = plural(countLines(resultText(item.result?.content)), 'linha', 'linhas')
  } else if (kind === 'search') {
    row.tag = item.name
    const subject = str(input.pattern) || str(input.query) || str(input.url)
    row.desc = str(input.path) ? `${subject} em ${str(input.path)}` : subject
    if (status === 'ok' && (item.name === 'Grep' || item.name === 'Glob')) {
      meta = plural(countLines(resultText(item.result?.content)), 'resultado', 'resultados')
    }
  } else if (kind === 'edit') {
    if (item.name === 'Write') row.label = 'Escrita'
    row.desc = str(input.file_path) || str(input.notebook_path)
    row.diff = diffCounts(toolDiff(item.name, input, item.result?.details ?? null))
  } else if (kind === 'bash') {
    const command = str(input.command).split('\n', 1)[0] ?? ''
    const description = str(input.description)
    row.desc = description || command
    row.mono = !description
    if (description && command) row.command = command
  } else if (kind === 'agent') {
    row.tag = item.subagent?.subagent_type || str(input.subagent_type) || undefined
    row.desc = item.subagent?.description || str(input.description)
    row.mono = false
  } else {
    row.desc = toolLabel(item.name)
  }
  if (item.result_missing) meta = 'Resultado não disponível no histórico'
  else if (status === 'idle' && !item.result) meta = 'sem resultado'
  row.meta = meta
  return row
}

const SUMMARY_ORDER: WorkKind[] = ['read', 'search', 'edit', 'bash', 'tool', 'agent']
const SUMMARY_WORDS: Record<WorkKind, [string, string]> = {
  read: ['leitura', 'leituras'],
  search: ['busca', 'buscas'],
  edit: ['edição', 'edições'],
  bash: ['comando', 'comandos'],
  tool: ['ferramenta', 'ferramentas'],
  agent: ['subagente', 'subagentes'],
}

/** "1 edição · 1 comando ok · 1 falhou": what the block did by kind, then what is running or failed. */
export function workSummary(items: ToolItem[], sessionActive: boolean): string {
  const counts = new Map<WorkKind, number>()
  let running = 0
  let failed = 0
  for (const item of items) {
    const status = workStatus(item, sessionActive)
    if (status === 'running') running++
    else if (status === 'error') failed++
    else counts.set(workKind(item), (counts.get(workKind(item)) ?? 0) + 1)
  }
  const parts = SUMMARY_ORDER.filter((k) => counts.has(k)).map((k) => {
    const [one, many] = SUMMARY_WORDS[k]
    return `${plural(counts.get(k)!, one, many)}${k === 'bash' ? ' ok' : ''}`
  })
  if (running) parts.push(`${running} rodando`)
  if (failed) parts.push(failed === 1 ? '1 falhou' : `${failed} falharam`)
  return parts.join(' · ')
}

/** What the block is doing now (its last running action), for the line shown while it is closed; empty when nothing runs. */
export function workActivity(items: ToolItem[], sessionActive: boolean): string {
  for (let i = items.length - 1; i >= 0; i--) {
    const item = items[i]!
    if (workStatus(item, sessionActive) !== 'running') continue
    const row = workRow(item, sessionActive)
    const what = row.kind === 'agent' ? item.subagent?.last_activity || row.desc : row.desc
    return [row.label === 'Escrita' ? WORK_LABEL.edit : WORK_LABEL[row.kind], what].filter(Boolean).join(' · ')
  }
  return ''
}

/**
 * A work block's rail node. The states win, in this order: something waits for the user, something
 * runs, something failed. Otherwise the node shows the kind of the block's first action.
 * `waiting` holds the `tool_use_id`s of the requests the user has yet to answer.
 */
export function groupNodeKind(items: ToolItem[], sessionActive: boolean, waiting?: ReadonlySet<string>): NodeKind {
  if (waiting && items.some((item) => waiting.has(item.tool_use_id))) return 'waiting'
  const statuses = items.map((item) => workStatus(item, sessionActive))
  if (statuses.includes('running')) return 'running'
  if (statuses.includes('error')) return 'error'
  return workKind(items[0]!)
}
