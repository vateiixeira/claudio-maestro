import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import * as api from '../api/http'
import type { Specialist, SpecialistCreate, SpecialistNotice, SpecialistRun, SpecialistUpdate } from '../types/api'

const RUNS_LIMIT = 50

/** Match the backend's started_at DESC, id DESC ordering. */
function compareRuns(a: SpecialistRun, b: SpecialistRun): number {
  return b.started_at - a.started_at || b.id - a.id
}

function isRun(value: unknown): value is SpecialistRun {
  const v = value as Partial<SpecialistRun> | null
  return !!v && typeof v === 'object' && typeof v.id === 'number' && typeof v.specialist_id === 'number' && typeof v.outcome === 'string'
}

function isNotice(value: unknown): value is SpecialistNotice {
  const v = value as Partial<SpecialistNotice> | null
  return !!v && typeof v === 'object' && typeof v.id === 'number' && typeof v.text === 'string'
}

/** The agents of the "Agentes" page and their notices; kept up to date by the `specialist.*` events. */
export const useSpecialistsStore = defineStore('specialists', () => {
  const list = ref<Specialist[]>([])
  const loaded = ref(false)
  const error = ref<string | null>(null)
  const notices = ref<SpecialistNotice[]>([])
  const noticesLoaded = ref(false)
  const noticesError = ref<string | null>(null)
  /** Runs of the agents whose detail was opened, newest first. */
  const runs = ref<Record<number, SpecialistRun[]>>({})
  /** Bumped by every `specialist.changed` of an agent: the detail rereads its files when it moves. */
  const changes = ref<Record<number, number>>({})
  const runLoads = new Map<number, { events: Map<number, SpecialistRun> }>()
  let ticket = 0
  const noticeListeners = new Set<(notice: SpecialistNotice) => void>()

  const unreadCount = computed(() => notices.value.filter((n) => n.read_at === null).length)

  function byId(id: number): Specialist | undefined {
    return list.value.find((s) => s.id === id)
  }

  function runsOf(id: number): SpecialistRun[] {
    return runs.value[id] ?? []
  }

  async function load(): Promise<void> {
    const mine = ++ticket
    try {
      const fresh = await api.listSpecialists()
      if (mine !== ticket) return
      list.value = fresh
      error.value = null
    } catch (e) {
      if (mine !== ticket) return
      error.value = api.errorMessage(e)
    } finally {
      if (mine === ticket) loaded.value = true
    }
  }

  async function loadRuns(id: number): Promise<void> {
    const request = { events: new Map<number, SpecialistRun>() }
    runLoads.set(id, request)
    try {
      const fresh = await api.listSpecialistRuns(id, RUNS_LIMIT)
      if (runLoads.get(id) !== request) return
      const merged = new Map(fresh.map((run) => [run.id, run]))
      for (const [key, run] of request.events) merged.set(key, run)
      const next = [...merged.values()].sort((a, b) => b.started_at - a.started_at || b.id - a.id)
      let completed = 0
      runs.value = { ...runs.value, [id]: next.filter((run) =>
        run.outcome === 'queued' || run.outcome === 'starting' || completed++ < RUNS_LIMIT,
      ) }
    } finally {
      if (runLoads.get(id) === request) runLoads.delete(id)
    }
  }

  async function loadNotices(): Promise<void> {
    try {
      notices.value = await api.listSpecialistNotices()
      noticesError.value = null
    } catch (e) {
      noticesError.value = api.errorMessage(e)
    } finally {
      noticesLoaded.value = true
    }
  }

  function replace(agent: Specialist): void {
    const index = list.value.findIndex((s) => s.id === agent.id)
    if (index >= 0) list.value.splice(index, 1, agent)
    else list.value.push(agent)
  }

  async function create(input: SpecialistCreate): Promise<Specialist> {
    const agent = await api.createSpecialist(input)
    replace(agent)
    return agent
  }

  async function update(id: number, changes: SpecialistUpdate): Promise<Specialist> {
    const agent = await api.updateSpecialist(id, changes)
    replace(agent)
    return agent
  }

  async function remove(id: number): Promise<void> {
    await api.deleteSpecialist(id)
    list.value = list.value.filter((s) => s.id !== id)
    runLoads.delete(id)
    const { [id]: _, ...rest } = runs.value
    runs.value = rest
  }

  /** A queued run has no session yet; a failed one carries the reason to show. */
  async function runNow(id: number, text?: string): Promise<SpecialistRun> {
    const run = await api.runSpecialist(id, text)
    applyRun(run)
    return run
  }

  async function cancelRun(id: number, runId: number): Promise<void> {
    applyRun(await api.cancelSpecialistRun(id, runId))
  }

  async function markRead(ids: number[]): Promise<void> {
    if (ids.length === 0) return
    await api.markSpecialistNoticesRead(ids)
    markReadLocally(ids)
  }

  function markReadLocally(ids: number[]): void {
    const wanted = new Set(ids)
    const now = Math.floor(Date.now() / 1000)
    notices.value = notices.value.map((n) => (wanted.has(n.id) && n.read_at === null ? { ...n, read_at: now } : n))
  }

  // Events -------------------------------------------------------------------

  /** `specialist.changed`: something about the agent (or it being removed) changed; the list is small, reread it. */
  function applyChanged(data: unknown): void {
    const id = (data as { id?: unknown } | null)?.id
    if (typeof id === 'number') changes.value = { ...changes.value, [id]: (changes.value[id] ?? 0) + 1 }
    void load()
  }

  /** `specialist.run`: a run started or ended. */
  function applyRun(data: unknown): void {
    if (!isRun(data)) return
    runLoads.get(data.specialist_id)?.events.set(data.id, data)
    const agent = byId(data.specialist_id)
    if (agent && (!agent.last_run || compareRuns(data, agent.last_run) <= 0)) agent.last_run = data
    const known = runs.value[data.specialist_id]
    if (!known) return
    const index = known.findIndex((r) => r.id === data.id)
    const next = [...known]
    if (index >= 0) next.splice(index, 1, data)
    else next.unshift(data)
    next.sort(compareRuns)
    let historyCount = 0
    // Pending work must stay available to cancel even after many newer runs finish.
    const kept = next.filter((run) => run.outcome === 'queued' || run.outcome === 'starting' || historyCount++ < RUNS_LIMIT)
    runs.value = { ...runs.value, [data.specialist_id]: kept }
  }

  /** `specialist.notice`: a new notice (the object) or `{read_ids}` when some were marked as read. */
  function applyNotice(data: unknown): void {
    const readIds = (data as { read_ids?: unknown } | null)?.read_ids
    if (Array.isArray(readIds)) {
      markReadLocally(readIds.filter((i): i is number => typeof i === 'number'))
      return
    }
    if (!isNotice(data) || notices.value.some((n) => n.id === data.id)) return
    notices.value = [data, ...notices.value]
    for (const listener of [...noticeListeners]) listener(data)
  }

  /** Calls `listener` for each notice that arrives by event (not the ones the list loads). Returns the function that stops it. */
  function onNewNotice(listener: (notice: SpecialistNotice) => void): () => void {
    noticeListeners.add(listener)
    return () => { noticeListeners.delete(listener) }
  }

  return {
    list, loaded, error, notices, noticesError, runs, changes, unreadCount,
    byId, runsOf, load, loadRuns, loadNotices, create, update, remove, runNow, cancelRun, markRead,
    applyChanged, applyRun, applyNotice, onNewNotice,
  }
})
