import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useLabelsStore } from '../labels'
import { jsonResponse, makeLabel, routeFetch } from '../../test/factories'

beforeEach(() => setActivePinia(createPinia()))
afterEach(() => vi.unstubAllGlobals())

describe('store de etiquetas', () => {
  it('carrega, cria, atualiza e remove', async () => {
    const store = useLabelsStore()
    const a = makeLabel({ id: 1, slug: 'a' })
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/labels': () => jsonResponse([a]) }))
    await store.load()
    expect(store.loaded).toBe(true)
    expect(store.byId(1)).toEqual(a)

    vi.stubGlobal('fetch', routeFetch({ 'POST /api/labels': () => jsonResponse(makeLabel({ id: 2, slug: 'b' }), 201) }))
    await store.create('b', '#000000')
    expect(store.labels.map((l) => l.id)).toEqual([1, 2])

    vi.stubGlobal('fetch', routeFetch({ 'PATCH /api/labels/1': () => jsonResponse({ ...a, color: '#00ff00' }) }))
    await store.update(1, { color: '#00ff00' })
    expect(store.byId(1)?.color).toBe('#00ff00')

    vi.stubGlobal('fetch', routeFetch({ 'DELETE /api/labels/1': () => new Response(null, { status: 204 }) }))
    await store.remove(1)
    expect(store.byId(1)).toBeUndefined()
  })

  it('uma carga antiga que chega depois não sobrescreve a nova', async () => {
    const store = useLabelsStore()
    let release!: (r: Response) => void
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>((r) => { release = r })))
    const first = store.load()
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/labels': () => jsonResponse([makeLabel({ id: 9, slug: 'novo' })]) }))
    await store.load()
    release(jsonResponse([makeLabel({ id: 1, slug: 'velho' })]))
    await first
    expect(store.labels.map((l) => l.slug)).toEqual(['novo'])
  })
})
