import type { ConversationItem } from '../types/conversation'
import { resultText, str } from './tool'

export type TaskStatus = 'pending' | 'in_progress' | 'completed'

export interface TaskEntry {
  id: string
  subject: string
  status: TaskStatus
}

export const TASK_TOOLS = new Set(['TaskCreate', 'TaskUpdate', 'TodoWrite'])

export const TASK_STATUS_LABEL: Record<TaskStatus, string> = {
  pending: 'Pendente',
  in_progress: 'Em andamento',
  completed: 'Concluída',
}

export function taskStatus(value: unknown): TaskStatus {
  return value === 'in_progress' || value === 'completed' ? value : 'pending'
}

/** Task id from a TaskCreate result such as "Task #3 created successfully". */
export function createdTaskId(content: unknown): string | null {
  return /#(\d+)/.exec(resultText(content))?.[1] ?? null
}

/**
 * The session's task list, rebuilt from the task tool calls in order, and the id of
 * the last item that changed it (where the full list is shown).
 */
export function deriveTasks(items: ConversationItem[]): { tasks: TaskEntry[]; lastItemId: string | null } {
  let tasks: TaskEntry[] = []
  let lastItemId: string | null = null
  for (const item of items) {
    if (item.type !== 'tool' || !TASK_TOOLS.has(item.name)) continue
    const input = item.input ?? {}
    if (item.name === 'TaskCreate') {
      const id = createdTaskId(item.result?.content) ?? `sem-id-${item.id}`
      tasks = [...tasks.filter((t) => t.id !== id), { id, subject: str(input.subject) || str(input.description), status: 'pending' }]
    } else if (item.name === 'TaskUpdate') {
      const id = String(input.taskId ?? '')
      tasks = tasks.map((t) => (t.id === id ? { ...t, status: taskStatus(input.status), subject: str(input.subject) || t.subject } : t))
    } else {
      const todos = Array.isArray(input.todos) ? input.todos : []
      tasks = todos.map((todo: Record<string, unknown>, i: number) => ({
        id: String(i + 1),
        subject: str(todo?.content),
        status: taskStatus(todo?.status),
      }))
    }
    lastItemId = item.id
  }
  return { tasks, lastItemId }
}
