import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useSessionsStore } from '../sessions'
import { makeSession } from '../../test/factories'

beforeEach(() => setActivePinia(createPinia()))
afterEach(() => vi.unstubAllGlobals())

describe('store de sessões', () => {
  it('aplica session.state à sessão certa', () => {
    const store = useSessionsStore()
    store.setForProject(1, [makeSession({ session_id: 'a' }), makeSession({ session_id: 'b' })])

    store.applyEvent({ session_id: 'b', seq: 3, type: 'session.state', data: { state: 'running', error: null } })

    expect(store.find('a')?.state).toBe('closed')
    expect(store.find('b')?.state).toBe('running')
  })

  it('guarda o erro de session.state', () => {
    const store = useSessionsStore()
    store.setForProject(1, [makeSession({ session_id: 'a' })])
    store.applyEvent({ session_id: 'a', seq: 1, type: 'session.state', data: { state: 'error', error: 'Caiu.' } })
    expect(store.find('a')).toMatchObject({ state: 'error', error: 'Caiu.' })
  })

  it('aplica session.title à sessão certa', () => {
    const store = useSessionsStore()
    store.setForProject(1, [makeSession({ session_id: 'a' })])
    store.setForProject(2, [makeSession({ session_id: 'c', project_id: 2 })])

    store.applyEvent({ session_id: 'c', seq: 1, type: 'session.title', data: { title: 'Corrigir o login' } })

    expect(store.find('c')?.title).toBe('Corrigir o login')
    expect(store.find('a')?.title).toBe('Nova sessão')
  })

  it('ignora eventos de sessão desconhecida', () => {
    const store = useSessionsStore()
    store.setForProject(1, [makeSession({ session_id: 'a' })])
    const before = JSON.stringify(store.byProject)

    store.applyEvent({ session_id: 'zzz', seq: 1, type: 'session.state', data: { state: 'running', error: null } })
    store.applyEvent({ session_id: 'zzz', seq: 2, type: 'session.title', data: { title: 'x' } })

    expect(JSON.stringify(store.byProject)).toBe(before)
  })

  it('ignora tipos que não são dele', () => {
    const store = useSessionsStore()
    store.setForProject(1, [makeSession({ session_id: 'a' })])
    store.applyEvent({ session_id: 'a', seq: 1, type: 'item.upsert', data: { title: 'x', state: 'running' } })
    expect(store.find('a')).toMatchObject({ title: 'Nova sessão', state: 'closed' })
  })

  it('cria sessão pela API e a coloca no topo do projeto', async () => {
    const created = makeSession({ session_id: 'nova' })
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(created), { status: 201 })))
    const store = useSessionsStore()
    store.setForProject(1, [makeSession({ session_id: 'velha' })])

    const session = await store.create(1)

    expect(session.session_id).toBe('nova')
    expect(store.forProject(1).map((s) => s.session_id)).toEqual(['nova', 'velha'])
    expect(fetch).toHaveBeenCalledWith('/api/projects/1/sessions', expect.objectContaining({ method: 'POST' }))
  })

  it('carrega as sessões de um projeto', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify([makeSession({ session_id: 'x' })]))))
    const store = useSessionsStore()
    await store.loadForProject(1)
    expect(store.forProject(1).map((s) => s.session_id)).toEqual(['x'])
    expect(store.forProject(99)).toEqual([])
  })

  it('session.updated com outro projeto tira a sessão do projeto antigo', () => {
    const store = useSessionsStore()
    store.setForProject(1, [makeSession({ session_id: 'a', project_id: 1 })])
    store.setForProject(2, [])

    store.applyEvent({ session_id: 'a', seq: 2, type: 'session.updated', data: makeSession({ session_id: 'a', project_id: 2 }) })

    expect(store.forProject(1)).toEqual([])
    expect(store.forProject(2).map((s) => s.session_id)).toEqual(['a'])
  })
})
