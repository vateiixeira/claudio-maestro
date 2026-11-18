import type { SubagentStatus, ToolItem } from '../types/conversation'
import { shortPath } from '../projectsList'
import { agentStatus } from './subagents'
import { commandFolder, str, toolLabel } from './tool'
import { editSucceeded } from './turns'
import { workKind, workRow, type WorkKind } from './work'

// What the work block groups and counts from its actions: the runs of the same kind, the folders,
// how long it took and the files and subagents it produced.

export const GROUP_LABEL: Record<WorkKind, string> = {
  bash: 'Comandos', read: 'Leituras', search: 'Buscas', edit: 'Edições', tool: 'Ferramenta', agent: 'Subagentes',
}

export interface WorkGroup<R> {
  /** The id of the first row. */
  key: string
  kind: WorkKind
  label: string
  /** "em ~/dev/app" for commands run in a folder, the tool for a tool, else empty. */
  where: string
  rows: R[]
}

function groupWhere(row: { item: ToolItem; kind: WorkKind; folder?: string }): string {
  if (row.kind === 'bash') return row.folder ? `em ${shortPath(row.folder)}` : ''
  if (row.kind === 'tool') return toolLabel(row.item.name)
  return ''
}

/** Consecutive rows of the same kind (and, for commands, the same folder; for tools, the same tool) as one group. */
export function workGroups<R extends { item: ToolItem; kind: WorkKind; folder?: string }>(rows: R[]): WorkGroup<R>[] {
  const groups: WorkGroup<R>[] = []
  for (const row of rows) {
    const last = groups.at(-1)
    const first = last?.rows[0]
    const same = last && first && first.kind === row.kind
      && (row.kind !== 'bash' || (first.folder ?? '') === (row.folder ?? ''))
      && (row.kind !== 'tool' || first.item.name === row.item.name)
    if (same) last.rows.push(row)
    else groups.push({ key: row.item.id, kind: row.kind, label: GROUP_LABEL[row.kind], where: groupWhere(row), rows: [row] })
  }
  return groups
}

/** The distinct folders the commands say they ran in (a leading `cd`). */
export function workFolders(items: ToolItem[]): number {
  const folders = new Set<string>()
  for (const item of items) {
    if (item.name !== 'Bash') continue
    const { folder } = commandFolder(str(item.input?.command))
    if (folder) folders.add(folder)
  }
  return folders.size
}

/** Seconds from the start of the first action to now (running) or to `endAt`; null without a start, without an end, or under 1 second. */
export function workSpan(items: ToolItem[], endAt: number | null | undefined, nowSeconds: number, running: boolean): number | null {
  const start = items[0]?.at
  if (start == null) return null
  const end = running ? nowSeconds : endAt
  if (end == null) return null
  const seconds = end - start
  return seconds >= 1 ? seconds : null
}

export interface WorkFile {
  path: string
  name: string
  added: number
  removed: number
  /** The last edit of the file. */
  itemId: string
}

export interface WorkAgent {
  itemId: string
  description: string
  status: SubagentStatus
  seconds: number | null
  startedAt: number | null
  tokens: number | null
}

/** The files the block edited (lines summed per path) and the subagents it launched. */
export function workArtifacts(items: ToolItem[], sessionActive: boolean): { files: WorkFile[]; agents: WorkAgent[] } {
  const files = new Map<string, WorkFile>()
  const agents: WorkAgent[] = []
  const seen = new Set<string>()
  for (const item of items) {
    if (seen.has(item.id)) continue
    seen.add(item.id)
    const kind = workKind(item)
    if (kind === 'edit') {
      const row = workRow(item, sessionActive)
      if (!row.desc || !editSucceeded(item)) continue
      const file = files.get(row.desc) ?? { path: row.desc, name: row.desc.split(/[/\\]/).filter(Boolean).at(-1) || row.desc, added: 0, removed: 0, itemId: item.id }
      file.added += row.diff?.added ?? 0
      file.removed += row.diff?.removed ?? 0
      file.itemId = item.id
      files.set(row.desc, file)
    } else if (kind === 'agent') {
      const sub = item.subagent
      const duration = sub?.usage?.duration_ms
      const seconds = duration != null ? duration / 1000
        : sub?.started_at != null && sub.last_activity_at != null ? sub.last_activity_at - sub.started_at : null
      agents.push({
        itemId: item.id,
        description: workRow(item, sessionActive).desc,
        status: agentStatus(item, sessionActive),
        seconds,
        startedAt: sub?.started_at ?? null,
        tokens: sub?.usage?.total_tokens ?? null,
      })
    }
  }
  return { files: [...files.values()], agents }
}
