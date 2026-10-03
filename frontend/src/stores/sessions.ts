import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import * as api from '../api/http'
import { deriveDisplay } from '../sessionState'
import type { Session, SessionMark, SessionUpdate } from '../types/api'
import type { SessionStateData, SessionTitleData, WsEvent } from '../types/events'

/** Sessions indexed by project, kept up to date by the session events. */
export const useSessionsStore = defineStore('sessions', () => {
  // Newest first, as the backend lists them.
  const byProject = ref<Record<number, Session[]>>({})
  const loaded = ref(false)

  // Ordering is by arrival, not by `seq`: the backend's `seq` restarts at 0 when it
  // restarts or drops a session from memory. `clock` ticks on every request and
  // event; a listing loses to an event of the same session that arrived after it was sent.
  let clock = 0
  const lastEventAt = new Map<string, number>()
  // Each listing of a project takes a ticket; only the newest ticket may write.
  const listTicket = new Map<number, number>()

  const all = computed<Session[]>(() =>
    Object.values(byProject.value)
      .flat()
      .sort((a, b) => b.last_activity_at - a.last_activity_at),
  )

  function forProject(projectId: number): Session[] {
    return byProject.value[projectId] ?? []
  }

  function find(sessionId: string): Session | undefined {
    for (const list of Object.values(byProject.value)) {
      const session = list.find((s) => s.session_id === sessionId)
      if (session) return session
    }
    return undefined
  }

  /** Keeps what an event brought if it arrived after the request (`sentAt`) left. */
  function fresher(incoming: Session, sentAt: number): Session {
    if ((lastEventAt.get(incoming.session_id) ?? 0) > sentAt) return find(incoming.session_id) ?? incoming
    return incoming
  }

  /**
   * The listing, plus sessions of the project it could not know yet: created or
   * announced by an event after the request (`sentAt`) left.
   */
  function merged(projectId: number, sessions: Session[], sentAt: number): Session[] {
    const listed = new Set(sessions.map((s) => s.session_id))
    const newer = forProject(projectId).filter(
      (s) => !listed.has(s.session_id) && (lastEventAt.get(s.session_id) ?? 0) > sentAt,
    )
    return [...newer, ...sessions.map((s) => fresher(s, sentAt))]
  }

  function setForProject(projectId: number, sessions: Session[], sentAt = Infinity): void {
    byProject.value[projectId] = merged(projectId, sessions, sentAt)
  }

  function forgetProject(projectId: number): void {
    delete byProject.value[projectId]
  }

  function takeTicket(projectId: number): number {
    const ticket = ++clock
    listTicket.set(projectId, ticket)
    return ticket
  }

  async function loadForProject(projectId: number): Promise<Session[]> {
    const ticket = takeTicket(projectId)
    const sessions = await api.listSessions(projectId)
    if (listTicket.get(projectId) === ticket) setForProject(projectId, sessions, ticket)
    return forProject(projectId)
  }

  /** Rereads the project's CLI history on the backend and takes the sessions it returns. */
  async function sync(projectId: number): Promise<Session[]> {
    const ticket = takeTicket(projectId)
    const list = await api.syncProject(projectId)
    if (listTicket.get(projectId) === ticket) setForProject(projectId, list, ticket)
    return forProject(projectId)
  }

  /** Reloads the given projects and drops any other. A failing project keeps what it had. */
  async function loadAll(projectIds: number[]): Promise<void> {
    const tickets = projectIds.map(takeTicket)
    const results = await Promise.allSettled(projectIds.map((id) => api.listSessions(id)))
    const next: Record<number, Session[]> = {}
    projectIds.forEach((id, index) => {
      const result = results[index]!
      const current = listTicket.get(id) === tickets[index]
      next[id] = result.status === 'fulfilled' && current ? merged(id, result.value, tickets[index]!) : forProject(id)
    })
    byProject.value = next
    loaded.value = true
  }

  /** Puts a whole session in place (new ones go to the top of their project). */
  function upsert(session: Session): void {
    // A session that moved to another project leaves the old one.
    for (const [id, other] of Object.entries(byProject.value)) {
      if (Number(id) === session.project_id) continue
      const at = other.findIndex((s) => s.session_id === session.session_id)
      if (at >= 0) other.splice(at, 1)
    }
    const list = forProject(session.project_id)
    const index = list.findIndex((s) => s.session_id === session.session_id)
    if (index >= 0) list.splice(index, 1, session)
    else byProject.value[session.project_id] = [session, ...list]
  }

  async function create(projectId: number, groupId: number | null = null): Promise<Session> {
    const session = await api.createSession(projectId, groupId)
    noteEvent(session.session_id)
    upsert(session)
    return session
  }

  /** Sends a PATCH and applies the answer unless an event arrived meanwhile. */
  async function patch(sessionId: string, changes: SessionUpdate): Promise<void> {
    const sentAt = ++clock
    const session = await api.updateSession(sessionId, changes)
    if ((lastEventAt.get(sessionId) ?? 0) > sentAt) return
    upsert(session)
  }

  async function setFinished(sessionId: string, finished: boolean): Promise<void> {
    await patch(sessionId, { finished })
  }

  async function rename(sessionId: string, title: string): Promise<void> {
    await patch(sessionId, { title })
  }

  async function setGroup(sessionId: string, groupId: number | null): Promise<void> {
    await patch(sessionId, { group_id: groupId })
  }

  async function setMark(
    sessionId: string,
    mark: SessionMark | null,
    extra: { mark_note?: string | null; mark_until?: number | null } = {},
  ): Promise<void> {
    await patch(sessionId, { mark, ...extra })
  }

  async function setPriority(sessionId: string, priority: boolean): Promise<void> {
    await patch(sessionId, { priority })
  }

  function noteEvent(sessionId: string): void {
    lastEventAt.set(sessionId, ++clock)
  }

  // Sessions looked up after an event about a session this tab did not know. Kept
  // after success so a session the listing hides (finished long ago) is looked up once.
  const fetching = new Set<string>()

  /** A session created elsewhere (e.g. another tab): finds its project and reloads it. */
  const gone = new Set<string>()
  function fetchUnknown(sessionId: string): void {
    if (fetching.has(sessionId) || gone.has(sessionId)) return
    fetching.add(sessionId)
    noteEvent(sessionId)
    api.getSession(sessionId)
      .then((snapshot) => (find(sessionId) ? undefined : loadForProject(snapshot.project_id)))
      .catch((e) => {
        fetching.delete(sessionId)
        // 404 is final: the session does not exist, asking again will not change that.
        if (e instanceof api.ApiError && e.status === 404) gone.add(sessionId)
      })
  }

  /** Applies `session.updated`, `session.state` and `session.title`; anything else is ignored. */
  function applyEvent(event: WsEvent): void {
    if (event.type === 'session.updated') {
      noteEvent(event.session_id)
      upsert(event.data as Session)
      return
    }
    const session = find(event.session_id)
    if (!session) {
      if (event.type === 'session.state' || event.type === 'session.title') fetchUnknown(event.session_id)
      return
    }
    if (event.type === 'session.state') {
      const data = event.data as SessionStateData
      noteEvent(event.session_id)
      session.state = data.state
      session.error = data.error ?? null
      Object.assign(
        session,
        deriveDisplay(data.state, session.finished, session.display_state, session.cli_running ?? false, session.subagents_running ?? false),
      )
      // The summary with the new pending prompt comes in a `session.updated`; until
      // then an old reason ("Pede permissão") must not stay on screen.
      if (data.state !== 'awaiting_decision') {
        session.pending_kind = null
        session.pending_permission = null
      }
      session.seq = event.seq
    } else if (event.type === 'session.title') {
      noteEvent(event.session_id)
      session.title = (event.data as SessionTitleData).title
      session.seq = event.seq
    }
  }

  return {
    byProject, loaded, all, forProject, find, setForProject, forgetProject,
    loadForProject, loadAll, sync, create, setFinished, rename, setGroup, setMark, setPriority, applyEvent,
  }
})
