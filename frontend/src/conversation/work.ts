import type { ToolItem } from '../types/conversation'
import { backgroundState } from './background'
import { diffCounts, toolDiff } from './diff'
import { agentStatus } from './subagents'
import { askedModel, countLines, resultText, str, toolLabel } from './tool'
import { AGENT_TOOLS, EDIT_TOOLS, SEARCH_TOOLS, toolRunning, type NodeKind } from './turns'

// What a work block (the actions between two statements) says about each of its actions.

export type WorkKind = 'bash' | 'tool' | 'read' | 'search' | 'edit' | 'agent'
export type WorkStatus = 'ok' | 'running' | 'waiting' | 'error' | 'stopped' | 'idle'

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

/**
 * `waiting` holds the `tool_use_id`s of the requests the user has yet to answer: the action they
 * belong to waits for the user, whatever it is doing (the same rule as the rail node).
 */
export function workStatus(item: ToolItem, sessionActive: boolean, waiting?: ReadonlySet<string>): WorkStatus {
  if (waiting?.has(item.tool_use_id)) return 'waiting'
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
  /** The model of a subagent, shown in a chip after the tag. */
  model?: string | null
  desc: string
  /** The description is a path or a command: monospaced. */
  mono: boolean
  status: WorkStatus
  meta?: string
  /** First line of a command that has a description, shown on a second line while the row is closed. */
  command?: string
  /** Lines added and removed by an edit. */
  diff?: { added: number; removed: number }
  /** When the action started (Unix seconds), when the history says. */
  at?: number
}

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`

// The lines an edit changed, by item: working them out is the costly part of a row, and the block
// asks for every row at each token. An item whose input or result was replaced is another entry.
const diffCache = new WeakMap<ToolItem, { input: unknown; result: unknown; counts: WorkRow['diff'] }>()

function editDiff(item: ToolItem): WorkRow['diff'] {
  const cached = diffCache.get(item)
  if (cached && cached.input === item.input && cached.result === item.result) return cached.counts
  const counts = diffCounts(toolDiff(item.name, item.input ?? {}, item.result?.details ?? null))
  diffCache.set(item, { input: item.input, result: item.result, counts })
  return counts
}

/** The compact line of one action in a work block. `origin` is the subagent a file write came from: it becomes the chip. */
export function workRow(item: ToolItem, sessionActive: boolean, waiting?: ReadonlySet<string>, origin?: string): WorkRow {
  const kind = workKind(item)
  const status = workStatus(item, sessionActive, waiting)
  const input = item.input ?? {}
  const row: WorkRow = { kind, desc: '', mono: true, status }
  if (item.at != null) row.at = item.at
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
    row.diff = editDiff(item)
    if (origin) row.tag = origin
  } else if (kind === 'bash') {
    const command = str(input.command).split('\n', 1)[0] ?? ''
    const description = str(input.description)
    row.desc = description || command
    row.mono = !description
    if (description && command) row.command = command
  } else if (kind === 'agent') {
    row.tag = item.subagent?.subagent_type || str(input.subagent_type) || undefined
    row.model = item.subagent?.model || askedModel(input)
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

const SUMMARY_WORDS: Record<WorkKind, [string, string]> = {
  read: ['leitura', 'leituras'],
  search: ['busca', 'buscas'],
  edit: ['edição', 'edições'],
  bash: ['comando', 'comandos'],
  tool: ['ferramenta', 'ferramentas'],
  agent: ['subagente', 'subagentes'],
}

/** What the block is doing now (its last running or waiting action), for the line shown while it is closed; empty when nothing runs. */
export function workActivity(items: ToolItem[], sessionActive: boolean, waiting?: ReadonlySet<string>): string {
  for (let i = items.length - 1; i >= 0; i--) {
    const item = items[i]!
    const status = workStatus(item, sessionActive, waiting)
    if (status !== 'running' && status !== 'waiting') continue
    const row = workRow(item, sessionActive, waiting)
    const what = row.kind === 'agent' ? item.subagent?.last_activity || row.desc : row.desc
    return [row.label === 'Escrita' ? WORK_LABEL.edit : WORK_LABEL[row.kind], what].filter(Boolean).join(' · ')
  }
  return ''
}

/** One sentence for a collapsed group, using only facts already present in the conversation. */
export function workCaption(items: ToolItem[], sessionActive: boolean, waiting?: ReadonlySet<string>): string {
  const states = items.map((item) => ({ item, status: workStatus(item, sessionActive, waiting) }))
  if (states.some(({ status }) => status === 'waiting')) return 'Esperando você'
  const failed = states.filter(({ status }) => status === 'error').length
  const failure = failed ? plural(failed, 'falhou', 'falharam') : ''
  const running = [...states].reverse().find(({ status }) => status === 'running')?.item
  if (running) {
    const description = running.subagent?.last_activity || running.subagent?.description || str(running.input?.description)
    return [description || workActivity([running], sessionActive, waiting), failure].filter(Boolean).join(' · ')
  }
  const completed = states.filter(({ status }) => status === 'ok').map(({ item }) => item)
  const parts: string[] = []
  const commands = completed.filter((item) => workKind(item) === 'bash').length
  if (commands) parts.push(`executou ${plural(commands, 'comando', 'comandos')}`)
  for (const kind of ['read', 'edit'] as const) {
    const matching = completed.filter((item) => workKind(item) === kind)
    if (!matching.length) continue
    const paths = new Set(matching.map((item) => str(item.input?.file_path) || str(item.input?.notebook_path)).filter(Boolean))
    if (paths.size && matching.every((item) => str(item.input?.file_path) || str(item.input?.notebook_path))) {
      const path = [...paths][0]!
      const subject = paths.size === 1 ? path.split(/[/\\]/).filter(Boolean).at(-1) || path : `${paths.size} arquivos`
      parts.push(`${kind === 'read' ? 'leu' : 'editou'} ${subject}`)
    } else parts.push(`fez ${plural(matching.length, ...SUMMARY_WORDS[kind])}`)
  }
  for (const kind of ['search', 'tool', 'agent'] as const) {
    const count = completed.filter((item) => workKind(item) === kind).length
    if (count) parts.push(`${kind === 'search' ? 'fez' : kind === 'agent' ? 'executou' : 'usou'} ${plural(count, ...SUMMARY_WORDS[kind])}`)
  }
  if (failure) parts.push(failure)
  const missing = states.filter(({ status }) => status === 'idle').length
  const stopped = states.filter(({ status }) => status === 'stopped').length
  if (missing) parts.push(`${plural(missing, 'ação', 'ações')} sem resultado`)
  if (stopped) parts.push(plural(stopped, 'ação interrompida', 'ações interrompidas'))
  const sentence = parts.join(', ')
  return sentence.charAt(0).toUpperCase() + sentence.slice(1)
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
