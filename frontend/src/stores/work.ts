import { defineStore } from 'pinia'
import { ref } from 'vue'
import { request } from '../api/http'
import type { WorkDetail, WorkFilter, WorkIdentity, WorkPage, WorkDecision, WorkMode, WorkNotice, WorkEventPage } from '../types/work'
export const useWorkStore = defineStore('work', () => {
  const catalog = ref<Record<string, WorkIdentity>>({})
  const details = ref<Record<number, WorkDetail>>({})
  const changeVersion = ref(0)
  const dispatcherEnabled = ref<boolean | null>(null)
  const detailTickets = new Map<number, number>()
  const coordinators = ref<Record<number, string>>({})
  function changed(_data?: unknown) { changeVersion.value++ }
  let catalogTicket = 0
  async function loadCatalog() {
    const ticket = ++catalogTicket
    const result = await request<Record<string, WorkIdentity>>('GET', '/api/work/sessions')
    if (ticket !== catalogTicket) return
    catalog.value = result
    coordinators.value = Object.fromEntries(Object.entries(result).filter(([, identity]) => identity.work_role === 'coordinator').map(([sid, identity]) => [identity.project_id, sid]))
  }
  async function runtime() { dispatcherEnabled.value = (await request<{ dispatcher_enabled: boolean }>('GET', '/api/work/runtime')).dispatcher_enabled }
  async function list(filter: WorkFilter = {}): Promise<WorkPage> {
    const query = new URLSearchParams()
    for (const [key, value] of Object.entries(filter)) if (value !== undefined && value !== '') query.set(key, String(value))
    return request('GET', `/api/work-items?${query}`)
  }
  async function loadDetail(id: number) {
    const ticket = (detailTickets.get(id) ?? 0) + 1
    detailTickets.set(id, ticket)
    const version = changeVersion.value
    const detail = await request<WorkDetail>('GET', `/api/work-items/${id}`)
    if (detailTickets.get(id) === ticket && version === changeVersion.value) details.value[id] = detail
    return detail
  }
  const eventPage = (id: number, before: number, limit = 50) => request<WorkEventPage>('GET', `/api/work-items/${id}/events?before=${before}&limit=${limit}`)
  async function openCoordinator(projectId: number) {
    const result = await request<{ session_id: string }>('POST', `/api/projects/${projectId}/cto`)
    catalogTicket++ // An older catalog request cannot erase this newly created session.
    coordinators.value[projectId] = result.session_id
    catalog.value[result.session_id] = { work_role: 'coordinator', project_id: projectId, work_item_id: null, work_attempt_id: null }
    return result.session_id
  }
  const decisions = (projectId?: number, itemId?: number) => request<{ items: WorkDecision[] }>('GET', '/api/work/decisions?' + new URLSearchParams({ pending_only: 'true', ...(projectId ? { project_id: String(projectId) } : {}), ...(itemId ? { item_id: String(itemId) } : {}) }))
  const mode = (projectId: number) => request<WorkMode>('GET', `/api/projects/${projectId}/work-mode`)
  const setMode = (projectId: number, action: string, fence_id?: string) => request<WorkMode>('POST', `/api/projects/${projectId}/work-mode`, { action, ...(fence_id ? { fence_id } : {}) })
  const feed = (projectId?: number) => request<{ items: WorkNotice[]; after: number }>('GET', projectId ? `/api/projects/${projectId}/work-feed?latest=true` : '/api/work/notifications?latest=true')
  return { catalog, details, changeVersion, dispatcherEnabled, coordinators, changed, list, loadDetail, eventPage, loadCatalog, runtime, openCoordinator, decisions, mode, setMode, feed }
})
