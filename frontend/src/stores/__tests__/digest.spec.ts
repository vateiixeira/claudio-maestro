import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { flushPromises } from '@vue/test-utils'
import { useDigestStore } from '../digest'
import { jsonResponse, routeFetch } from '../../test/factories'
import type { SessionDigest } from '../../types/api'

const digest = (over: Partial<SessionDigest> = {}): SessionDigest => ({
  session_id: 's1', read_at: 100, short: 'Faz X', phases: [], plan_done: false, error: null, error_at: null, ...over,
})

beforeEach(() => setActivePinia(createPinia()))
afterEach(() => vi.unstubAllGlobals())

describe('store do agente de resumos', () => {
  it('carrega o resumo de uma sessão', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/sessions/s1/digest': () => jsonResponse(digest()) }))
    const store = useDigestStore()
    await store.load('s1')
    expect(store.digests.s1?.short).toBe('Faz X')
  })

  it('guarda null para sessão sem resumo', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/sessions/s1/digest': () => jsonResponse(null) }))
    const store = useDigestStore()
    await store.load('s1')
    expect(store.digests.s1).toBeNull()
  })

  it('pedido fica pendente até o evento chegar', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'POST /api/sessions/s1/digest': () => jsonResponse({ queued: true }, 202) }))
    const store = useDigestStore()
    await store.request('s1')
    expect(store.pending.s1).toBe(true)
    store.applyDigest({ session_id: 's1', digest: digest({ short: 'Novo' }) })
    expect(store.pending.s1).toBe(false)
    expect(store.digests.s1?.short).toBe('Novo')
  })

  it('falha no pedido desfaz o pendente e guarda o erro', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'POST /api/sessions/s1/digest': () => jsonResponse({ detail: 'Sessão não encontrada.' }, 404) }))
    const store = useDigestStore()
    await store.request('s1')
    expect(store.pending.s1).toBe(false)
    expect(store.errors.s1).toBe('Sessão não encontrada.')
  })

  it('ignora eventos malformados', () => {
    const store = useDigestStore()
    store.applyDigest(null)
    store.applyDigest({ session_id: 3 })
    store.applyStatus('x')
    expect(store.digests).toEqual({})
    expect(store.status).toBeNull()
  })

  it('aplica o estado e invalida os resumos na reconexão', async () => {
    const store = useDigestStore()
    store.applyStatus({ enabled: true, running: false, next_run_at: 1, paused_until: null })
    expect(store.status?.enabled).toBe(true)
    store.applyDigest({ session_id: 's1', digest: digest() })
    store.invalidate()
    await flushPromises()
    expect('s1' in store.digests).toBe(false)
  })
})
