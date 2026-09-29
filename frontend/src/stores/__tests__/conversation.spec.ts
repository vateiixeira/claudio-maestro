import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { applyConversationEvent, emptyConversation, useConversationStore } from '../conversation'
import { jsonResponse, makeEvent, makeSnapshot, routeFetch } from '../../test/factories'

const text = (id: string, t: string, streaming = false) => ({
  type: 'text', id, text: t, streaming, parent_tool_use_id: null,
})

describe('redutor da conversa', () => {
  it('upsert insere e substitui pelo id', () => {
    const state = emptyConversation('s1')
    applyConversationEvent(state, makeEvent('item.upsert', text('a', 'oi'), 1))
    applyConversationEvent(state, makeEvent('item.upsert', text('b', 'x'), 2))
    applyConversationEvent(state, makeEvent('item.upsert', text('a', 'olá'), 3))
    expect(state.items.map((i) => i.id)).toEqual(['a', 'b'])
    expect((state.items[0] as { text: string }).text).toBe('olá')
    expect(state.seq).toBe(3)
  })

  it('append concatena ao texto', () => {
    const state = emptyConversation('s1')
    applyConversationEvent(state, makeEvent('item.upsert', text('a', 'Ol', true), 1))
    applyConversationEvent(state, makeEvent('item.append', { item_id: 'a', text: 'á' }, 2))
    expect((state.items[0] as { text: string }).text).toBe('Olá')
  })

  it('ignora eventos com seq antigo', () => {
    const state = emptyConversation('s1')
    state.seq = 5
    expect(applyConversationEvent(state, makeEvent('item.upsert', text('a', 'x'), 5))).toBe(false)
    expect(applyConversationEvent(state, makeEvent('item.upsert', text('a', 'x'), 4))).toBe(false)
    expect(state.items).toEqual([])
  })

  it('prompt.request adiciona e prompt.resolved remove', () => {
    const state = emptyConversation('s1')
    const prompt = { prompt_id: 'p1', tool_name: 'Bash', input: { command: 'ls' }, can_always: true }
    applyConversationEvent(state, makeEvent('prompt.request', prompt, 1))
    applyConversationEvent(state, makeEvent('prompt.request', prompt, 2))
    expect(state.prompts).toHaveLength(1)
    applyConversationEvent(state, makeEvent('prompt.resolved', { prompt_id: 'p1', decision: 'cancelled' }, 3))
    expect(state.prompts).toEqual([])
  })

  it('aplica estado, título, init e resultado do turno', () => {
    const state = emptyConversation('s1')
    applyConversationEvent(state, makeEvent('session.state', { state: 'error', error: 'caiu' }, 1))
    applyConversationEvent(state, makeEvent('session.title', { title: 'T' }, 2))
    applyConversationEvent(state, makeEvent('session.init', { session_id: 's1', model: 'haiku', permission_mode: 'default' }, 3))
    applyConversationEvent(state, makeEvent('turn.result', { subtype: 'success', is_error: false, duration_ms: 1200, total_cost_usd: 0.01 }, 4))
    expect(state.state).toBe('error')
    expect(state.error).toBe('caiu')
    expect(state.title).toBe('T')
    expect(state.init?.model).toBe('haiku')
    expect(state.lastResult?.duration_ms).toBe(1200)
  })
})

describe('store da conversa', () => {
  beforeEach(() => setActivePinia(createPinia()))
  afterEach(() => vi.unstubAllGlobals())

  it('guarda eventos durante o carregamento e aplica só os mais novos que o retrato', async () => {
    let release!: (r: Response) => void
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/sessions/s1': () => new Promise<Response>((resolve) => { release = resolve }),
    }))
    const store = useConversationStore()
    const loading = store.load('s1')
    store.receive(makeEvent('item.upsert', text('a', 'velho'), 2))
    store.receive(makeEvent('item.upsert', text('b', 'novo'), 4))
    expect(store.get('s1')?.items ?? []).toEqual([])
    release(jsonResponse(makeSnapshot({ seq: 3, items: [text('a', 'retrato') as never] })))
    await loading
    const conv = store.get('s1')!
    expect(conv.items.map((i) => (i as { text: string }).text)).toEqual(['retrato', 'novo'])
    expect(conv.seq).toBe(4)
  })
})
