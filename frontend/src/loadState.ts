import { computed, type ComputedRef } from 'vue'
import { useProjectsStore } from './stores/projects'
import { useSessionsStore } from './stores/sessions'

export type LoadState = 'loading' | 'error' | 'ready'

/**
 * Whether the conversation lists can be trusted yet. Before the first load, and
 * when the projects failed to load, an empty list means "unknown", not "none".
 */
export function useLoadState(): ComputedRef<LoadState> {
  const projects = useProjectsStore()
  const sessions = useSessionsStore()
  return computed(() => {
    if (sessions.loaded) return 'ready'
    return projects.loadError ? 'error' : 'loading'
  })
}
