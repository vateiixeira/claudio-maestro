import { formatTokens } from '../format'
import type { ToolItem } from '../types/conversation'
import { applyTaskTool, type TaskEntry } from './tasks'
import type { Turn } from './turns'
import { commandFolder, str } from './tool'
import { workActivity, workStatus } from './work'

// What the end of a turn says while the turn runs (the task list and the live line) and after it.

export interface TurnTaskState {
  /** The session's task list as it stood when the turn ended (or as it is now, for the running turn). */
  tasks: TaskEntry[]
  /** The turn called a task tool (TodoWrite, TaskCreate, TaskUpdate). */
  touched: boolean
}

/** The task list at the end of each turn, carried over from the turns before it, and whether the turn changed it. */
export function turnTaskStates(turns: Turn[]): TurnTaskState[] {
  let tasks: TaskEntry[] = []
  return turns.map((turn) => {
    for (const call of turn.taskCalls) tasks = applyTaskTool(tasks, call)
    return { tasks, touched: turn.taskCalls.length > 0 }
  })
}

/**
 * A finished turn shows the list only when it touched it, so a chat unrelated to the plan does not
 * repeat it. The running turn shows the list in force while something is left to do, or when it
 * touched the list itself.
 */
export function showTurnTasks(state: TurnTaskState, done: boolean): boolean {
  if (!state.tasks.length) return false
  if (done) return state.touched
  return state.touched || state.tasks.some((task) => task.status !== 'completed')
}

/**
 * What the running turn is doing now, for the live line: waiting for the user, the action that runs
 * (the same text as a closed work block), writing, or else thinking.
 */
export function liveActivity(turn: Turn, sessionActive: boolean, waiting: ReadonlySet<string>, asking: boolean): string {
  if (asking || waiting.size) return 'esperando você'
  const tools: ToolItem[] = []
  let writing = false
  for (const entry of turn.entries) {
    if (entry.kind === 'group') tools.push(...entry.items)
    else if (entry.item.type === 'tool') tools.push(entry.item)
    else if (entry.item.type === 'text' && entry.item.streaming) writing = true
  }
  return workActivity(tools, sessionActive, waiting) || (writing ? 'Escrevendo' : 'Pensando')
}

/**
 * The command under the live line: the first line of what runs, without its leading `cd <folder> &&`.
 * It belongs to the action the line names (the last that runs), and only a command that has a
 * description needs it: without one, the line already says the command.
 */
export function liveDetail(turn: Turn, sessionActive: boolean, waiting: ReadonlySet<string>): string {
  const tools: ToolItem[] = []
  for (const entry of turn.entries) {
    if (entry.kind === 'group') tools.push(...entry.items)
    else if (entry.item.type === 'tool') tools.push(entry.item)
  }
  const current = [...tools].reverse().find((item) => {
    const status = workStatus(item, sessionActive, waiting)
    return status === 'running' || status === 'waiting'
  })
  if (!current || current.name !== 'Bash' || workStatus(current, sessionActive, waiting) !== 'running') return ''
  if (!str(current.input?.description).trim()) return ''
  const { rest } = commandFolder(str(current.input?.command))
  return rest.split('\n').find((line) => line.trim())?.trim() ?? ''
}

/** "353 tokens", "1,6 mil tokens"; empty when the count is not known yet. */
export function tokensLabel(tokens: number | null | undefined): string {
  if (tokens == null || !Number.isFinite(tokens) || tokens <= 0) return ''
  return tokens === 1 ? '1 token' : `${formatTokens(tokens)} tokens`
}
