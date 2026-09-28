import type { EventSocket } from '../api/socket'
import { useProjectsStore } from './projects'
import { useSessionsStore } from './sessions'

/** Loads projects and then the sessions of each one. */
export async function loadEverything(): Promise<void> {
  const projects = useProjectsStore()
  const sessions = useSessionsStore()
  await projects.load()
  await sessions.loadAll(projects.projects.map((p) => p.id))
}

/**
 * Feeds `session.state` and `session.title` into the sessions store, and reloads
 * everything after the socket comes back (events sent while it was down are lost).
 */
export function bindRealtime(socket: EventSocket): () => void {
  const sessions = useSessionsStore()
  const offs = [
    socket.on('session.state', (event) => sessions.applyEvent(event)),
    socket.on('session.title', (event) => sessions.applyEvent(event)),
    socket.onReconnect(() => {
      loadEverything().catch(() => {
        // The projects store keeps the error; the sidebar shows it.
      })
    }),
  ]
  return () => offs.forEach((off) => off())
}
