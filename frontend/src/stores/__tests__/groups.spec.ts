import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useGroupsStore } from '../groups'
import { useSessionsStore } from '../sessions'
import { jsonResponse, makeGroup, makeSession, routeFetch } from '../../test/factories'

beforeEach(() => setActivePinia(createPinia()))
afterEach(() => vi.unstubAllGlobals())

describe('store de agrupadores', () => {
  it('carrega, cria, renomeia e remove', async () => {
    const store = useGroupsStore()
    const a = makeGroup({ id: 1, project_id: 1, name: 'A' })
    const b = makeGroup({ id: 2, project_id: 2, name: 'B' })
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/groups': () => jsonResponse([a, b]) }))
    await store.load()
    expect(store.loaded).toBe(true)
    expect(store.forProject(1)).toEqual([a])

    vi.stubGlobal('fetch', routeFetch({ 'POST /api/projects/1/groups': () => jsonResponse(makeGroup({ id: 3, name: 'C' }), 201) }))
    await store.create(1, 'C')
    expect(store.forProject(1).map((g) => g.id)).toEqual([1, 3])

    vi.stubGlobal('fetch', routeFetch({ 'PATCH /api/groups/1': () => jsonResponse({ ...a, name: 'Z' }) }))
    await store.rename(1, 'Z')
    expect(store.byId(1)?.name).toBe('Z')

    vi.stubGlobal('fetch', routeFetch({ 'DELETE /api/groups/1': () => new Response(null, { status: 204 }) }))
    await store.remove(1)
    expect(store.byId(1)).toBeUndefined()

    store.forgetProject(2)
    expect(store.byId(2)).toBeUndefined()
  })

  it('uma carga antiga que chega depois não sobrescreve a nova', async () => {
    const store = useGroupsStore()
    let release!: (r: Response) => void
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>((r) => { release = r })))
    const first = store.load()
    const firstRelease = release
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse([makeGroup({ id: 2 })])))
    await store.load()
    firstRelease(jsonResponse([makeGroup({ id: 1 })]))
    await first
    expect(store.groups.map((g) => g.id)).toEqual([2])
  })

  it('cria sessão dentro do agrupador e move uma sessão', async () => {
    const sessions = useSessionsStore()
    const bodies: unknown[] = []
    vi.stubGlobal('fetch', routeFetch({
      'POST /api/projects/1/sessions': (init) => { bodies.push(JSON.parse(String(init?.body))); return jsonResponse(makeSession({ group_id: 4 }), 201) },
    }))
    await sessions.create(1, 4)
    expect(bodies).toEqual([{ group_id: 4 }])

    vi.stubGlobal('fetch', routeFetch({
      'PATCH /api/sessions/s1': (init) => { bodies.push(JSON.parse(String(init?.body))); return jsonResponse(makeSession({ group_id: null })) },
    }))
    await sessions.setGroup('s1', null)
    expect(bodies[1]).toEqual({ group_id: null })
    expect(sessions.find('s1')?.group_id).toBeNull()
  })

  it('criar sessão sem agrupador não manda corpo', async () => {
    const sessions = useSessionsStore()
    const init = vi.fn()
    vi.stubGlobal('fetch', routeFetch({
      'POST /api/projects/1/sessions': (i) => { init(i?.body); return jsonResponse(makeSession(), 201) },
    }))
    await sessions.create(1)
    expect(init).toHaveBeenCalledWith(undefined)
  })
})
