import type { EventSocket } from '../api/socket'
import { useClosureStore } from './closure'
import { useDeliveriesStore } from './deliveries'
import { useDigestStore } from './digest'
import { useGitStore } from './git'
import { useGitDetailsStore } from './gitDetails'
import { useGroupsStore } from './groups'
import { useLayoutStore } from './layout'
import { useModelsStore } from './models'
import { useProjectsStore } from './projects'
import { useSessionsStore } from './sessions'
import { useUpdatesStore } from './updates'
import { useUsageStore } from './usage'

/** Loads projects and then the sessions of each one. */
export async function loadEverything(): Promise<void> {
  const projects = useProjectsStore()
  const sessions = useSessionsStore()
  await projects.load()
  const git = useGitStore()
  // Branches are secondary: a failure leaves the project without them.
  projects.projects.forEach((p) => void git.load(p.id).catch(() => {}))
  useGitDetailsStore().reloadOpen()
  void useModelsStore().reload()
  // The version line is secondary: a failure only hides it.
  void useUpdatesStore().load().catch(() => {})
  // The usage meter is secondary: a failure keeps the last numbers.
  void useUsageStore().load().catch(() => {})
  // A failure leaves the menu without groups until the next load.
  void useGroupsStore().load().catch(() => {})
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
    socket.on('session.updated', (event) => sessions.applyEvent(event)),
    // The index was reread from the CLI history: sessions and hidden counts changed.
    socket.on('project.synced', (event) => {
      const projectId = (event.data as { project_id?: number } | null)?.project_id
      if (typeof projectId !== 'number') return
      sessions.loadForProject(projectId).catch(() => {})
      useProjectsStore().load().catch(() => {})
    }),
    // Created, renamed or removed in some project: the list is small, reload it all.
    socket.on('groups.changed', () => {
      useGroupsStore().load().catch(() => {})
    }),
    socket.on('project.git', (event) => useGitStore().applyEvent(event)),
    socket.on('models.updated', (event) => {
      useModelsStore().apply((event.data as { models?: unknown } | null)?.models)
    }),
    socket.on('app.update', (event) => useUpdatesStore().apply(event.data)),
    socket.on('app.update.progress', (event) => useUpdatesStore().applyProgress(event.data)),
    socket.on('app.usage', (event) => useUsageStore().apply(event.data)),
    // The digest agent wrote a summary, or its state changed (both global events).
    socket.on('session.digest', (event) => useDigestStore().applyDigest(event.data)),
    socket.on('digest.status', (event) => useDigestStore().applyStatus(event.data)),
    socket.on('session.closure', (event) => useClosureStore().applyClosure(event.data)),
    // A delivery record was created or changed (global event).
    socket.on('delivery.updated', (event) => useDeliveriesStore().applyEvent(event.data)),
    socket.onReconnect(() => {
      useDigestStore().invalidate()
      useClosureStore().invalidate()
      void useDigestStore().refreshStatus()
      // Events sent while the socket was down are lost: reread the day on screen.
      const deliveries = useDeliveriesStore()
      if (deliveries.date) void deliveries.load(deliveries.date)
      // The startup read of the preferences failed: read them again now.
      const layout = useLayoutStore()
      if (!layout.loadedFromServer) void layout.restore()
      loadEverything().catch(() => {
        // The projects store keeps the error; the sidebar shows it.
      })
    }),
  ]
  return () => offs.forEach((off) => off())
}
