import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { applyConversationEvent, conversationFromSnapshot, emptyConversation, useConversationStore } from '../conversation'
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

  it('conversation.reset recarrega o retrato e mostra os itens novos', async () => {
    let calls = 0
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/sessions/s1': () => {
        calls += 1
        return calls === 1
          ? jsonResponse(makeSnapshot({ seq: 2, items: [text('a', 'antigo') as never] }))
          : jsonResponse(makeSnapshot({ seq: 5, items: [text('a', 'antigo') as never, text('b', 'de fora') as never] }))
      },
    }))
    const store = useConversationStore()
    await store.load('s1')

    store.receive(makeEvent('conversation.reset', {}, 5))
    store.receive(makeEvent('item.upsert', text('c', 'nova'), 6))
    await flushPromises()

    expect(calls).toBe(2)
    expect(store.get('s1')!.items.map((i) => (i as { text: string }).text)).toEqual(['antigo', 'de fora', 'nova'])
  })

  it('não faz cargas concorrentes: um pedido durante a carga recarrega ao final', async () => {
    const releases: ((r: Response) => void)[] = []
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/sessions/s1': () => new Promise<Response>((resolve) => { releases.push(resolve) }),
    }))
    const store = useConversationStore()
    const first = store.load('s1')
    const second = store.load('s1')
    const third = store.load('s1')
    await flushPromises()
    expect(releases).toHaveLength(1)
    releases[0]!(jsonResponse(makeSnapshot({ seq: 1, items: [text('a', 'velho') as never] })))
    await flushPromises()
    expect(releases).toHaveLength(2)
    releases[1]!(jsonResponse(makeSnapshot({ seq: 2, items: [text('b', 'novo') as never] })))
    const results = await Promise.all([first, second, third])
    expect(releases).toHaveLength(2)
    for (const conv of results) expect(conv.items.map((i) => (i as { text: string }).text)).toEqual(['novo'])
    expect(store.get('s1')!.seq).toBe(2)
  })

  it('conversation.reset durante uma carga mais velha carrega de novo', async () => {
    const releases: ((r: Response) => void)[] = []
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/sessions/s1': () => new Promise<Response>((resolve) => { releases.push(resolve) }),
    }))
    const store = useConversationStore()
    const loading = store.load('s1')
    store.receive(makeEvent('conversation.reset', {}, 3))
    releases[0]!(jsonResponse(makeSnapshot({ seq: 2, items: [text('a', 'velho') as never] })))
    await flushPromises()
    releases[1]!(jsonResponse(makeSnapshot({ seq: 3, items: [text('b', 'novo') as never] })))
    await loading
    expect(store.get('s1')!.items.map((i) => (i as { text: string }).text)).toEqual(['novo'])
  })
})

describe('session.updated na conversa', () => {
  it('aplica o título vindo de outra aba', () => {
    const state = emptyConversation('s1')
    state.title = 'Antigo'
    applyConversationEvent(state, makeEvent('session.updated', { session_id: 's1', title: 'Novo', state: 'idle', error: null }, 1))
    expect(state.title).toBe('Novo')
  })
})

describe('opções da sessão', () => {
  it('lê do retrato e aplica session.options', () => {
    const conv = conversationFromSnapshot({
      ...makeSnapshot({ seq: 1 }),
      model: 'sonnet', model_resolved: 'claude-sonnet-5', effort: 'medium', permission_mode: 'acceptEdits', effort_pending: false,
    } as never)
    expect(conv.options).toEqual({ model: 'sonnet', model_resolved: 'claude-sonnet-5', effort: 'medium', permission_mode: 'acceptEdits', effort_pending: false })
    applyConversationEvent(conv, makeEvent('session.options', { model: 'opus', model_resolved: null, effort: 'high', permission_mode: 'plan', effort_pending: true }, 2))
    expect(conv.options).toEqual({ model: 'opus', model_resolved: null, effort: 'high', permission_mode: 'plan', effort_pending: true })
  })

  it('retrato sem opções usa nulos', () => {
    const conv = conversationFromSnapshot(makeSnapshot() as never)
    expect(conv.options).toEqual({ model: null, model_resolved: null, effort: null, permission_mode: null, effort_pending: false })
  })
})
