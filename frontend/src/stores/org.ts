import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'
import * as api from '../api/http'
import { isActive } from '../groupList'
import { ACTIVE_RUN_OUTCOMES as ACTIVE_OUTCOMES, TURN_OPEN_STATES } from '../org'
import { useSessionsStore } from './sessions'
import type { Router } from 'vue-router'
import type { Agent, Decision, Notice, Routine, Run } from '../types/org'

const RUNS_LIMIT = 50

export interface TreeNode {
  agent: Agent
  children: TreeNode[]
}

const byName = (a: Agent, b: Agent) => a.name.localeCompare(b.name, 'pt-BR') || a.id - b.id

/** Newest first, as the backend orders them (started_at DESC, id DESC). */
function compareRuns(a: Run, b: Run): number {
  return b.started_at - a.started_at || b.id - a.id
}

function isRun(value: unknown): value is Run {
  const v = value as Partial<Run> | null
  return !!v && typeof v === 'object' && typeof v.id === 'number' && typeof v.agent_id === 'number' && typeof v.outcome === 'string'
}

function isNotice(value: unknown): value is Notice {
  const v = value as Partial<Notice> | null
  return !!v && typeof v === 'object' && typeof v.id === 'number' && typeof v.text === 'string'
}

function isDecision(value: unknown): value is Decision {
  const v = value as Partial<Decision> | null
  return !!v && typeof v === 'object' && typeof v.id === 'number' && typeof v.status === 'string'
}

function idOf(data: unknown, key: string): number | null {
  const value = (data as Record<string, unknown> | null)?.[key]
  return typeof value === 'number' ? value : null
}

/**
 * The agents of the organization (all projects), their runs, routines and notices, and the decisions waiting for the
 * person. Kept up to date by the `agent.*` and `decision` events.
 */
export const useOrgStore = defineStore('org', () => {
  const agents = ref<Agent[]>([])
  const loaded = ref(false)
  const error = ref<string | null>(null)
  const notices = ref<Notice[]>([])
  const noticesLoaded = ref(false)
  const noticesError = ref<string | null>(null)
  /** Runs of the agents whose runs were opened, newest first. */
  const runs = ref<Record<number, Run[]>>({})
  /** Routines of the projects whose routines were opened. */
  const routines = ref<Record<number, Routine[]>>({})
  /** The decisions waiting for the person, newest first. */
  const decisionsPending = ref<Decision[]>([])
  /** Bumped by every `agent.changed` (and announcement) of an agent: its panel rereads the files when it moves. */
  const changes = ref<Record<number, number>>({})

  const runLoads = new Map<number, { events: Map<number, Run> }>()
  const agentTickets = new Map<number, number>()
  /** Agents this screen deleted: their removal event must not make the store reread (and 404) them. */
  const deleted = new Set<number>()
  let listTicket = 0
  const noticeListeners = new Set<(notice: Notice) => void>()

  const unreadCount = computed(() => notices.value.filter((n) => n.read_at === null).length)

  function byId(id: number): Agent | undefined {
    return agents.value.find((a) => a.id === id)
  }

  function byProject(projectId: number): Agent[] {
    return agents.value.filter((a) => a.project_id === projectId).sort(byName)
  }

  /** The agents of a project grouped by boss, the top ones first; every level ordered by name. */
  function tree(projectId: number): TreeNode[] {
    const mine = byProject(projectId)
    const ids = new Set(mine.map((a) => a.id))
    const children = new Map<number, Agent[]>()
    const roots: Agent[] = []
    for (const agent of mine) {
      // A boss that is not in the project (it should not happen) leaves the agent on top instead of hiding it.
      if (agent.reports_to !== null && ids.has(agent.reports_to)) {
        children.set(agent.reports_to, [...(children.get(agent.reports_to) ?? []), agent])
      } else {
        roots.push(agent)
      }
    }
    const build = (agent: Agent): TreeNode => ({ agent, children: (children.get(agent.id) ?? []).map(build) })
    return roots.map(build)
  }

  /** The agent with no boss in the project (the first by name). */
  function topOf(projectId: number): Agent | undefined {
    return tree(projectId)[0]?.agent
  }

  /** The agent whose main conversation is this session, if any. */
  function isMainSession(sessionId: string): Agent | undefined {
    return agents.value.find((a) => a.main_session_id === sessionId)
  }

  function runsOf(agentId: number): Run[] {
    return runs.value[agentId] ?? []
  }

  function routinesOf(projectId: number): Routine[] {
    return routines.value[projectId] ?? []
  }

  async function load(): Promise<void> {
    const mine = ++listTicket
    try {
      const fresh = await api.listAgents()
      if (mine !== listTicket) return
      agents.value = fresh
      for (const agent of fresh) deleted.delete(agent.id)
      error.value = null
    } catch (e) {
      if (mine !== listTicket) return
      error.value = api.errorMessage(e)
    } finally {
      if (mine === listTicket) loaded.value = true
    }
  }

  /** Puts an agent the API answered with in the list right away (replacing it in place, or adding it). */
  function upsertAgent(agent: Agent): void {
    deleted.delete(agent.id) // the id came back (a new agent may take the id of a deleted one)
    const index = agents.value.findIndex((a) => a.id === agent.id)
    if (index >= 0) agents.value.splice(index, 1, agent)
    else agents.value.push(agent)
  }

  /** Drops an agent and what was loaded for it. */
  function removeAgent(agentId: number): void {
    agents.value = agents.value.filter((a) => a.id !== agentId)
    runLoads.delete(agentId)
    const { [agentId]: _, ...rest } = runs.value
    runs.value = rest
  }

  /**
   * Deletes the agent on the server; the caller drops it with `removeAgent` once the screen has left it. The id
   * is remembered before the request, because the `agent.changed` of the removal can arrive before the answer;
   * a failure forgets it again.
   */
  async function deleteAgent(agentId: number): Promise<void> {
    deleted.add(agentId)
    try {
      await api.deleteAgent(agentId)
    } catch (e) {
      deleted.delete(agentId)
      throw e
    }
  }

  /** Rereads one agent. A 404 means it is gone; any other failure keeps what the list had. */
  async function refreshAgent(agentId: number): Promise<void> {
    if (deleted.has(agentId)) return
    const ticket = (agentTickets.get(agentId) ?? 0) + 1
    agentTickets.set(agentId, ticket)
    try {
      const fresh = await api.getAgent(agentId)
      if (agentTickets.get(agentId) === ticket) upsertAgent(fresh)
    } catch (e) {
      if (agentTickets.get(agentId) === ticket && e instanceof api.ApiError && e.status === 404) removeAgent(agentId)
    }
  }

  /**
   * Opens the agent's main conversation (the backend creates it on first use) and goes to it.
   * `router` is the caller's; without it only the session id is resolved. Errors propagate: the caller shows them.
   */
  async function openMain(id: number, router?: Pick<Router, 'push'>): Promise<string> {
    const sessionId = (await api.openAgentMain(id)).session_id
    const agent = byId(id)
    if (agent) agent.main_session_id = sessionId
    await router?.push({ name: 'session', params: { id: sessionId } })
    return sessionId
  }

  async function loadRuns(agentId: number): Promise<void> {
    const request = { events: new Map<number, Run>() }
    runLoads.set(agentId, request)
    try {
      const fresh = await api.listAgentRuns(agentId, RUNS_LIMIT)
      if (runLoads.get(agentId) !== request) return
      // What arrived by event while the request was in flight is newer than the response.
      const merged = new Map(fresh.map((run) => [run.id, run]))
      for (const [key, run] of request.events) merged.set(key, run)
      runs.value = { ...runs.value, [agentId]: limitRuns([...merged.values()].sort(compareRuns)) }
    } finally {
      if (runLoads.get(agentId) === request) runLoads.delete(agentId)
    }
  }

  /** The last 50 finished runs plus every run in flight. */
  function limitRuns(sorted: Run[]): Run[] {
    let finished = 0
    return sorted.filter((run) => ACTIVE_OUTCOMES.has(run.outcome) || finished++ < RUNS_LIMIT)
  }

  async function loadRoutines(projectId: number): Promise<void> {
    routines.value = { ...routines.value, [projectId]: await api.listRoutines(projectId) }
  }

  async function loadDecisions(): Promise<void> {
    decisionsPending.value = await api.listDecisions({ pending: true })
  }

  async function loadNotices(): Promise<void> {
    try {
      notices.value = await api.listAgentNotices()
      noticesError.value = null
    } catch (e) {
      noticesError.value = api.errorMessage(e)
    } finally {
      noticesLoaded.value = true
    }
  }

  /** Rereads the runs and routines that were opened (after the socket came back: events were lost). */
  async function reloadOpen(): Promise<void> {
    await Promise.allSettled([
      ...Object.keys(runs.value).map((id) => loadRuns(Number(id))),
      ...Object.keys(routines.value).map((id) => loadRoutines(Number(id))),
    ])
  }

  async function markRead(ids: number[]): Promise<void> {
    if (ids.length === 0) return
    await api.markAgentNoticesRead(ids)
    markReadLocally(ids)
  }

  function markReadLocally(ids: number[]): void {
    const wanted = new Set(ids)
    const now = Math.floor(Date.now() / 1000)
    notices.value = notices.value.map((n) => (wanted.has(n.id) && n.read_at === null ? { ...n, read_at: now } : n))
  }

  // The backend counts a main conversation that waits for an answer in `unseen`, but only when the agent is read, and
  // it publishes nothing when the wait begins or ends. So the store rereads the list when that wait changes.
  // The key holds just the mains that wait now: a list reload that changes nothing about it does not fire again.
  const sessions = useSessionsStore()
  const waitingMains = computed(() => {
    const mains = new Set(agents.value.map((a) => a.main_session_id).filter((id): id is string => id != null))
    return sessions.all
      .filter((s) => mains.has(s.session_id) && isActive(s) && (Boolean(s.pending_kind) || s.state === 'awaiting_decision'))
      .map((s) => s.session_id)
      .sort()
      .join(',')
  })
  watch(waitingMains, () => { void load() })

  // `busy` also counts an open turn in any session of the agent, and the backend publishes nothing when that turn
  // closes (`concluir` runs inside the turn, so the announcement is reread while it is still open). So the store
  // rereads the agents whose open-turn status changed. The key holds just the ids with an open turn now.
  const turnOpenAgents = computed(() => {
    const ids = new Set<number>()
    for (const s of sessions.all) {
      if (s.agent_id != null && TURN_OPEN_STATES.has(s.state)) ids.add(s.agent_id)
    }
    return [...ids].sort((a, b) => a - b).join(',')
  })
  watch(turnOpenAgents, (now, before) => {
    const parse = (key: string) => new Set(key ? key.split(',').map(Number) : [])
    const [after, previous] = [parse(now), parse(before)]
    for (const id of new Set([...after, ...previous])) {
      if (after.has(id) !== previous.has(id)) void refreshAgent(id)
    }
  })

  // Events -------------------------------------------------------------------

  function bump(agentId: number): void {
    changes.value = { ...changes.value, [agentId]: (changes.value[agentId] ?? 0) + 1 }
  }

  /** `agent.changed`: something about the agent (a file, a routine, the agent itself, or its removal) changed. */
  function applyChanged(data: unknown): void {
    const id = idOf(data, 'id')
    if (id === null) return
    bump(id)
    // The routines of its project may have changed too.
    const projectId = byId(id)?.project_id
    if (projectId !== undefined && routines.value[projectId]) void loadRoutines(projectId).catch(() => {})
    void refreshAgent(id)
  }

  /** `agent.announcement`: a run announced something. The `unseen` count is the server's, so the agent is reread. */
  function applyAnnouncement(data: unknown): void {
    const id = idOf(data, 'agent_id')
    if (id === null) return
    bump(id)
    void refreshAgent(id)
  }

  /** `agent.run`: a run started or ended (the whole run). */
  function applyRun(data: unknown): void {
    if (!isRun(data)) return
    runLoads.get(data.agent_id)?.events.set(data.id, data)
    const agent = byId(data.agent_id)
    if (agent && (!agent.last_run || compareRuns(data, agent.last_run) <= 0)) agent.last_run = data
    const known = runs.value[data.agent_id]
    if (!known) return
    const index = known.findIndex((r) => r.id === data.id)
    const next = [...known]
    if (index >= 0) next.splice(index, 1, data)
    else next.push(data)
    runs.value = { ...runs.value, [data.agent_id]: limitRuns(next.sort(compareRuns)) }
  }

  /** `agent.notice`: a new notice (the object) or `{read_ids}` when some were marked as read. */
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

  /** `decision`: the whole decision. A pending one is listed; an answered or expired one leaves the list. */
  function applyDecision(data: unknown): void {
    if (!isDecision(data)) return
    const others = decisionsPending.value.filter((d) => d.id !== data.id)
    if (data.status !== 'pending') {
      decisionsPending.value = others
      return
    }
    const known = decisionsPending.value.findIndex((d) => d.id === data.id)
    if (known >= 0) {
      const next = [...decisionsPending.value]
      next.splice(known, 1, data)
      decisionsPending.value = next
    } else {
      decisionsPending.value = [data, ...others]
    }
  }

  /** Routes an event of the socket by its type; types of other stores are ignored. */
  function applyEvent(type: string, data: unknown): void {
    switch (type) {
      case 'agent.changed': return applyChanged(data)
      case 'agent.announcement': return applyAnnouncement(data)
      case 'agent.run': return applyRun(data)
      case 'agent.notice': return applyNotice(data)
      case 'decision': return applyDecision(data)
    }
  }

  /** Calls `listener` for each notice that arrives by event (not the ones the list loads). Returns the function that stops it. */
  function onNewNotice(listener: (notice: Notice) => void): () => void {
    noticeListeners.add(listener)
    return () => { noticeListeners.delete(listener) }
  }

  return {
    agents, loaded, error, notices, noticesLoaded, noticesError, runs, routines, decisionsPending, changes, unreadCount,
    byId, byProject, tree, topOf, isMainSession, runsOf, routinesOf, upsertAgent, removeAgent, deleteAgent,
    load, loadNotices, loadRuns, loadRoutines, loadDecisions, reloadOpen, openMain, markRead, applyEvent, onNewNotice,
  }
})
