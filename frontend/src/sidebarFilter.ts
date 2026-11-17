import { ref } from 'vue'
import { needsYou } from './conversation/needsYou'
import type { Session } from './types/api'

export type SidebarFilter = 'running' | 'waiting' | 'unread'

/** The filter of the sidebar's open conversations. Memory only: it lasts while the page is open. */
export const sidebarFilter = ref<SidebarFilter | null>(null)

/** Whether a conversation shows with the filter on; `null` (no filter) accepts everything. */
export function matchesSidebarFilter(s: Session, filter: SidebarFilter | null): boolean {
  if (filter === null) return true
  if (filter === 'running') return s.display_state === 'running'
  if (filter === 'waiting') return s.display_state === 'waiting' && needsYou(s)
  return s.unread
}

/** The chip text: the count and what it counts, in the singular or plural. */
export function sidebarFilterLabel(filter: SidebarFilter, n: number): string {
  if (filter === 'running') return `${n} rodando`
  if (filter === 'waiting') return `${n} aguardando você`
  return `${n} ${n === 1 ? 'não lida' : 'não lidas'}`
}
