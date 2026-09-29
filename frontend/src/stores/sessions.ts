import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import * as api from '../api/http'
import { deriveDisplay } from '../sessionState'
import type { Session } from '../types/api'
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

  function setForProject(projectId: number, sessions: Session[], sentAt = Infinity): void {
    byProject.value[projectId] = sessions.map((s) => fresher(s, sentAt))
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
      next[id] = result.status === 'fulfilled' && current ? result.value.map((s) => fresher(s, tickets[index]!)) : forProject(id)
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

  async function create(projectId: number): Promise<Session> {
    const session = await api.createSession(projectId)
    upsert(session)
    return session
  }

  /** Sends a PATCH and applies the answer unless an event arrived meanwhile. */
  async function patch(sessionId: string, changes: { finished?: boolean; title?: string }): Promise<void> {
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

  function noteEvent(sessionId: string): void {
    lastEventAt.set(sessionId, ++clock)
  }

  /** Applies `session.updated`, `session.state` and `session.title`; anything else is ignored. */
  function applyEvent(event: WsEvent): void {
    if (event.type === 'session.updated') {
      noteEvent(event.session_id)
      upsert(event.data as Session)
      return
    }
    const session = find(event.session_id)
    if (!session) return
    if (event.type === 'session.state') {
      const data = event.data as SessionStateData
      noteEvent(event.session_id)
      session.state = data.state
      session.error = data.error ?? null
      Object.assign(session, deriveDisplay(data.state, session.finished, session.display_state))
      session.seq = event.seq
    } else if (event.type === 'session.title') {
      noteEvent(event.session_id)
      session.title = (event.data as SessionTitleData).title
      session.seq = event.seq
    }
  }

  return {
    byProject, loaded, all, forProject, find, setForProject, forgetProject,
    loadForProject, loadAll, sync, create, setFinished, rename, applyEvent,
  }
})
