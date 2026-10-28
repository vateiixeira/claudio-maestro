import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as api from '../api/http'
import type { Comment, Task, TaskCreate, TaskDetail, TaskEvent, TaskFilter, TaskUpdate } from '../types/org'

/**
 * The task changed since the screen read it (409): `task` is the current one, already reloaded, and the change was
 * not applied. `stale` says the cause was an old revision, not a rule of the board.
 */
export class TaskConflictError extends Error {
  readonly task: Task | null
  readonly stale: boolean

  constructor(message: string, task: Task | null, stale: boolean) {
    super(message)
    this.name = 'TaskConflictError'
    this.task = task
    this.stale = stale
  }
}

interface ListEntry {
  filter: TaskFilter
  items: Task[]
  loadedAt: number
  /** An event moved a task of this list: the next `list` reads it again. */
  stale: boolean
}

/** The same filter, whatever the order of its keys or of its statuses, is the same cache entry. */
function filterKey(filter: TaskFilter): string {
  const status = filter.status === undefined ? undefined : [...(Array.isArray(filter.status) ? filter.status : [filter.status])].sort()
  const normalized: Record<string, unknown> = { ...filter, ...(status ? { status } : {}) }
  return JSON.stringify(Object.fromEntries(Object.entries(normalized).filter(([, v]) => v !== undefined).sort(([a], [b]) => a.localeCompare(b))))
}

function isTaskEvent(value: unknown): value is TaskEvent {
  const v = value as Partial<TaskEvent> | null
  return !!v && typeof v === 'object' && typeof v.id === 'number' && typeof v.project_id === 'number'
}

/** The tasks of the board (lists by filter and the detail of each opened one), kept up to date by the `task` event. */
export const useTasksStore = defineStore('tasks', () => {
  const lists = ref<Record<string, ListEntry>>({})
  const details = ref<Record<number, TaskDetail>>({})
  /** Bumped by every event: a screen that shows a list watches it and calls `list` again. */
  const version = ref(0)
  const detailTickets = new Map<number, number>()
  const listTickets = new Map<string, number>()
  let invalidations = 0

  /**
   * The tasks that match the filter. Cached by filter; read again only after an event marked it stale.
   * A failure propagates and leaves no entry (or the old one, still stale).
   */
  async function list(filter: TaskFilter = {}): Promise<Task[]> {
    const key = filterKey(filter)
    const known = lists.value[key]
    if (known && !known.stale) return known.items
    const ticket = (listTickets.get(key) ?? 0) + 1
    listTickets.set(key, ticket)
    const startedAt = invalidations
    const items = await api.listTasks(filter)
    // The newest request wins. An event while this one was in flight may have changed what it read, so the entry is
    // stored stale (conservative: the next `list` reads it again).
    if (listTickets.get(key) === ticket) {
      lists.value = { ...lists.value, [key]: { filter, items, loadedAt: Date.now(), stale: invalidations !== startedAt } }
    }
    return items
  }

  function invalidateLists(projectId?: number): void {
    invalidations++
    const next: Record<string, ListEntry> = {}
    for (const [key, entry] of Object.entries(lists.value)) {
      const hit = projectId === undefined || entry.filter.project_id === undefined || entry.filter.project_id === projectId
      next[key] = hit ? { ...entry, stale: true } : entry
    }
    lists.value = next
    version.value++
  }

  /** Rereads the task with its comments, runs, decisions, PRs and CI; always the newest answer wins. */
  async function refresh(id: number): Promise<TaskDetail> {
    const ticket = (detailTickets.get(id) ?? 0) + 1
    detailTickets.set(id, ticket)
    const detail = await api.getTask(id)
    if (detailTickets.get(id) === ticket) details.value = { ...details.value, [id]: detail }
    return detail
  }

  /** The cached detail, or the one read now. */
  async function detail(id: number): Promise<TaskDetail> {
    return details.value[id] ?? refresh(id)
  }

  async function create(body: TaskCreate): Promise<Task> {
    const task = await api.createTask(body)
    invalidateLists(task.project_id)
    return task
  }

  /** Stores the task the server returned in the opened detail, if there is one, and rereads the rest in the background. */
  function adopt(task: Task): void {
    const open = details.value[task.id]
    if (!open) return
    details.value = { ...details.value, [task.id]: { ...open, task } }
    void refresh(task.id).catch(() => {})
  }

  /** A 409: reload the task and tell the caller, who decides what to do. Nothing is applied again. */
  async function conflict(id: number, error: api.ApiError, expectedRevision: number): Promise<never> {
    let fresh: Task | null = null
    try {
      fresh = (await refresh(id)).task
    } catch {
      // The screen shows the message; the task stays as it was.
    }
    invalidateLists(fresh?.project_id)
    throw new TaskConflictError(error.message, fresh, fresh !== null && fresh.revision !== expectedRevision)
  }

  /** Changes the task if it is still at `body.expected_revision`; a 409 is a `TaskConflictError`. */
  async function update(id: number, body: TaskUpdate): Promise<Task> {
    try {
      const task = await api.updateTask(id, body)
      invalidateLists(task.project_id)
      adopt(task)
      return task
    } catch (e) {
      if (e instanceof api.ApiError && e.status === 409) return conflict(id, e, body.expected_revision)
      throw e
    }
  }

  async function unblock(id: number, revision: number): Promise<Task> {
    try {
      const task = await api.unblockTask(id, revision)
      invalidateLists(task.project_id)
      adopt(task)
      return task
    } catch (e) {
      if (e instanceof api.ApiError && e.status === 409) return conflict(id, e, revision)
      throw e
    }
  }

  async function comment(id: number, text: string): Promise<Comment> {
    const created = await api.commentTask(id, text)
    const open = details.value[id]
    if (open && !open.comments.some((c) => c.id === created.id)) {
      details.value = { ...details.value, [id]: { ...open, comments: [...open.comments, created] } }
    }
    return created
  }

  // Events -------------------------------------------------------------------

  /**
   * `task`: something changed in a task. The lists of its project go stale; the detail is reread only when it was
   * opened here, so a task of another project creates nothing.
   */
  function applyEvent(data: unknown): void {
    if (!isTaskEvent(data)) return
    invalidateLists(data.project_id)
    if (details.value[data.id]) void refresh(data.id).catch(() => {})
  }

  /** `decision`: a decision of a task that is open changed, so its detail is reread. */
  function applyDecision(data: unknown): void {
    const taskId = (data as { task_id?: unknown } | null)?.task_id
    if (typeof taskId === 'number' && details.value[taskId]) void refresh(taskId).catch(() => {})
  }

  /** After the socket came back, events were lost: every list is stale and the opened details are reread. */
  function invalidateAll(): void {
    invalidateLists()
    for (const id of Object.keys(details.value)) void refresh(Number(id)).catch(() => {})
  }

  return { lists, details, version, list, detail, refresh, create, update, comment, unblock, applyEvent, applyDecision, invalidateAll }
})
