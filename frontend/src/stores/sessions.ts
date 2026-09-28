import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as api from '../api/http'
import type { Session } from '../types/api'
import type { SessionStateData, SessionTitleData, WsEvent } from '../types/events'

/** Sessions indexed by project, kept up to date by `session.state` and `session.title`. */
export const useSessionsStore = defineStore('sessions', () => {
  // Newest first, as the backend lists them.
  const byProject = ref<Record<number, Session[]>>({})
  const loaded = ref(false)

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

  function setForProject(projectId: number, sessions: Session[]): void {
    byProject.value[projectId] = sessions
  }

  function forgetProject(projectId: number): void {
    delete byProject.value[projectId]
  }

  async function loadForProject(projectId: number): Promise<Session[]> {
    const sessions = await api.listSessions(projectId)
    setForProject(projectId, sessions)
    return sessions
  }

  /** Reloads the given projects and drops any other. A failing project keeps what it had. */
  async function loadAll(projectIds: number[]): Promise<void> {
    const results = await Promise.allSettled(projectIds.map((id) => api.listSessions(id)))
    const next: Record<number, Session[]> = {}
    projectIds.forEach((id, index) => {
      const result = results[index]!
      next[id] = result.status === 'fulfilled' ? result.value : forProject(id)
    })
    byProject.value = next
    loaded.value = true
  }

  async function create(projectId: number): Promise<Session> {
    const session = await api.createSession(projectId)
    setForProject(projectId, [session, ...forProject(projectId).filter((s) => s.session_id !== session.session_id)])
    return session
  }

  /** Applies `session.state` and `session.title`; anything else, or an unknown session, is ignored. */
  function applyEvent(event: WsEvent): void {
    const session = find(event.session_id)
    if (!session) return
    if (event.type === 'session.state') {
      const data = event.data as SessionStateData
      session.state = data.state
      session.error = data.error ?? null
    } else if (event.type === 'session.title') {
      session.title = (event.data as SessionTitleData).title
    }
  }

  return { byProject, loaded, forProject, find, setForProject, forgetProject, loadForProject, loadAll, create, applyEvent }
})
