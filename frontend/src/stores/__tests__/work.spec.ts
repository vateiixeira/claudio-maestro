import { beforeEach, afterEach, describe, it, expect, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useWorkStore } from '../work'
import { jsonResponse } from '../../test/factories'
beforeEach(() => setActivePinia(createPinia()))
afterEach(() => vi.unstubAllGlobals())
describe('trabalho persistente', () => {
  it('usa os filtros e a paginação reais', async () => {
    const fetch = vi.fn((_url: string, _init?: RequestInit) => Promise.resolve(jsonResponse({ items: [], total: 82, limit: 30, offset: 30 })))
    vi.stubGlobal('fetch', fetch)
    const store = useWorkStore()
    const page = await store.list({ project_id: 2, status: 'active', source: 'sentry', limit: 30, offset: 30 })
    expect(page.total).toBe(82)
    expect(fetch.mock.calls[0]?.[0]).toBe('/api/work-items?project_id=2&status=active&source=sentry&limit=30&offset=30')
  })
  it('não sobrescreve o detalhe novo com HTTP anterior a um evento da mesma revisão', async () => {
    let release!: (value: Response) => void
    const first = new Promise<Response>(resolve => { release = resolve })
    const newer = { item: { id: 7, revision: 1, status: 'active' }, attempts: [{ id: 2, state: 'running' }] }
    vi.stubGlobal('fetch', vi.fn().mockReturnValueOnce(first).mockResolvedValueOnce(jsonResponse(newer)))
    const store = useWorkStore()
    const old = store.loadDetail(7)
    store.changed({ item_id: 7, revision: 1, project_id: 2 })
    await store.loadDetail(7)
    release(jsonResponse({ item: { id: 7, revision: 1, status: 'ready' }, attempts: [] }))
    await old
    expect(store.details[7]?.item.status).toBe('active')
  })
})

it('descarta catálogo HTTP antigo e remove CTOs que deixaram o catálogo', async () => {
  let release!: (value: Response) => void
  const old = new Promise<Response>(resolve => { release = resolve })
  vi.stubGlobal('fetch', vi.fn().mockReturnValueOnce(old).mockResolvedValueOnce(jsonResponse({ fresh: { work_role: 'coordinator', project_id: 2 } })).mockResolvedValueOnce(jsonResponse({})))
  const store = useWorkStore()
  const pending = store.loadCatalog()
  await store.loadCatalog()
  release(jsonResponse({ stale: { work_role: 'coordinator', project_id: 1 } }))
  await pending
  expect(store.catalog).toHaveProperty('fresh')
  expect(store.catalog).not.toHaveProperty('stale')
  await store.loadCatalog()
  expect(store.coordinators).toEqual({})
})
