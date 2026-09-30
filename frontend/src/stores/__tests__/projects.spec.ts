import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useProjectsStore } from '../projects'
import { useSessionsStore } from '../sessions'
import { useGroupsStore } from '../groups'
import { jsonResponse, makeGroup, makeProject, makeSession } from '../../test/factories'

beforeEach(() => setActivePinia(createPinia()))
afterEach(() => vi.unstubAllGlobals())

describe('store de projetos', () => {
  it('carrega, cria, renomeia e remove', async () => {
    const store = useProjectsStore()
    const a = makeProject({ id: 1, name: 'a' })
    const b = makeProject({ id: 2, name: 'b', position: 1 })

    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse([a])))
    await store.load()
    expect(store.loaded).toBe(true)
    expect(store.projects.map((p) => p.id)).toEqual([1])

    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(b, 201)))
    await store.create({ name: 'b', path: b.path, color: b.color })
    expect(store.projects.map((p) => p.id)).toEqual([1, 2])

    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ ...a, name: 'novo' })))
    await store.rename(1, 'novo')
    expect(store.byId(1)?.name).toBe('novo')

    const sessions = useSessionsStore()
    sessions.setForProject(2, [makeSession({ project_id: 2 })])
    useGroupsStore().groups = [makeGroup({ id: 5, project_id: 2 })]
    vi.stubGlobal('fetch', vi.fn(async () => new Response(null, { status: 204 })))
    await store.remove(2)
    expect(store.projects.map((p) => p.id)).toEqual([1])
    expect(sessions.forProject(2)).toEqual([])
    expect(useGroupsStore().groups).toEqual([])
  })

  it('propaga o erro da API ao criar', async () => {
    const store = useProjectsStore()
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ detail: 'Pasta já usada.' }, 409)))
    await expect(store.create({ name: 'x', path: '/x', color: '#B28CFF' })).rejects.toThrow('Pasta já usada.')
    expect(store.projects).toEqual([])
  })
})
