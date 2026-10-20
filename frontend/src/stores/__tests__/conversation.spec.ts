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
    for (const conv of results) expect(conv!.items.map((i) => (i as { text: string }).text)).toEqual(['novo'])
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

  it('guarda o contexto do retrato e o atualizado por evento', () => {
    const usage = { used_tokens: 84_000, max_tokens: 200_000, percent: 42 }
    const state = conversationFromSnapshot({ ...makeSnapshot({ seq: 1 }), context: usage })
    expect(state.context).toEqual(usage)
    const next = { used_tokens: 100_000, max_tokens: 200_000, percent: 50 }
    applyConversationEvent(state, makeEvent('session.updated', { session_id: 's1', title: '', context: next }, 2))
    expect(state.context).toEqual(next)
    applyConversationEvent(state, makeEvent('session.updated', { session_id: 's1', title: '' }, 3))
    expect(state.context).toEqual(next)
  })
})

describe('opções da sessão', () => {
  it('lê do retrato e aplica session.options', () => {
    const conv = conversationFromSnapshot({
      ...makeSnapshot({ seq: 1 }),
      model: 'sonnet', model_resolved: 'claude-sonnet-5', effort: 'medium', permission_mode: 'acceptEdits', effort_pending: false,
    } as never)
    expect(conv.options).toEqual({ model: 'sonnet', model_resolved: 'claude-sonnet-5', effort: 'medium', permission_mode: 'acceptEdits', effort_pending: false, remote_control: false, remote_control_state: 'off', remote_control_url: null, remote_control_error: null })
    applyConversationEvent(conv, makeEvent('session.options', { model: 'opus', model_resolved: null, effort: 'high', permission_mode: 'plan', effort_pending: true, remote_control: true, remote_control_state: 'on', remote_control_url: 'https://claude.ai/code/s', remote_control_error: null }, 2))
    expect(conv.options).toEqual({ model: 'opus', model_resolved: null, effort: 'high', permission_mode: 'plan', effort_pending: true, remote_control: true, remote_control_state: 'on', remote_control_url: 'https://claude.ai/code/s', remote_control_error: null })
  })

  it('retrato sem opções usa nulos', () => {
    const conv = conversationFromSnapshot(makeSnapshot() as never)
    expect(conv.options).toEqual({ model: null, model_resolved: null, effort: null, permission_mode: null, effort_pending: false, remote_control: false, remote_control_state: 'off', remote_control_url: null, remote_control_error: null })
  })
})

describe('conversa fechada antes do retrato chegar', () => {
  afterEach(() => vi.unstubAllGlobals())

  function pendingFetch() {
    const resolvers: Array<(response: Response) => void> = []
    const fetchMock = vi.fn(() => new Promise<Response>((resolve) => { resolvers.push(resolve) }))
    vi.stubGlobal('fetch', fetchMock)
    return { fetchMock, respond: (index: number, body: unknown) => resolvers[index]!(jsonResponse(body)) }
  }

  it('descarta a resposta de uma conversa que foi liberada no meio da carga', async () => {
    const { respond } = pendingFetch()
    const store = useConversationStore()
    const loaded = store.load('s1')
    store.forget('s1')
    respond(0, makeSnapshot({ seq: 3, items: [text('a', 'Tarde demais') as never] }))
    await expect(loaded).resolves.toBeNull()
    await flushPromises()
    expect(store.get('s1')).toBeUndefined()
    expect(Object.keys(store.bySession)).toEqual([])
  })

  it('não reinicia o aviso de atividade externa de uma conversa descartada', async () => {
    vi.useFakeTimers()
    try {
      const { respond } = pendingFetch()
      const store = useConversationStore()
      const loaded = store.load('s1')
      store.forget('s1')
      respond(0, makeSnapshot({ seq: 1, external_activity: true }))
      await loaded
      expect(vi.getTimerCount()).toBe(0)
    } finally {
      vi.useRealTimers()
    }
  })

  it('reabrir a conversa logo em seguida prevalece: busca de novo e grava o retrato novo', async () => {
    const { fetchMock, respond } = pendingFetch()
    const store = useConversationStore()
    const first = store.load('s1')
    store.forget('s1')
    const second = store.load('s1')
    respond(0, makeSnapshot({ seq: 1, items: [text('a', 'Velho') as never] }))
    await flushPromises()
    expect(fetchMock).toHaveBeenCalledTimes(2)
    respond(1, makeSnapshot({ seq: 2, items: [text('a', 'Novo') as never] }))
    const [a, b] = await Promise.all([first, second])
    expect(a).not.toBeNull()
    expect(b).not.toBeNull()
    expect((store.get('s1')!.items[0] as { text: string }).text).toBe('Novo')
  })

  it('uma recarga já pedida não ressuscita a conversa liberada', async () => {
    const { fetchMock, respond } = pendingFetch()
    const store = useConversationStore()
    const first = store.load('s1')
    void store.load('s1') // e.g. the socket reopened
    store.forget('s1')
    respond(0, makeSnapshot({ seq: 1 }))
    await first
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(store.get('s1')).toBeUndefined()
  })

  it('carregar de novo depois de liberada continua funcionando', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/sessions/s1': () => jsonResponse(makeSnapshot({ seq: 1 })) }))
    const store = useConversationStore()
    await store.load('s1')
    store.forget('s1')
    await expect(store.load('s1')).resolves.not.toBeNull()
    expect(store.get('s1')).toBeDefined()
  })
})

describe('tokens e início do turno em andamento', () => {
  beforeEach(() => setActivePinia(createPinia()))
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('turn.tokens guarda os tokens de saída do turno', () => {
    const state = emptyConversation('s1')
    expect(state.turnTokens).toBe(0)
    applyConversationEvent(state, makeEvent('turn.tokens', { output_tokens: 1600 }, 1))
    expect(state.turnTokens).toBe(1600)
    applyConversationEvent(state, makeEvent('turn.tokens', { output_tokens: 0 }, 2))
    expect(state.turnTokens).toBe(0)
  })

  it('o snapshot traz os tokens do turno (ausente vale zero)', () => {
    expect(conversationFromSnapshot(makeSnapshot({ turn_output_tokens: 353 })).turnTokens).toBe(353)
    expect(conversationFromSnapshot(makeSnapshot()).turnTokens).toBe(0)
  })

  it('turn.started guarda o início que o backend registrou; um turno novo o substitui', () => {
    const state = emptyConversation('s1')
    expect(state.runningSince).toBeNull()
    applyConversationEvent(state, makeEvent('turn.started', { started_at: 1000 }, 1))
    expect(state.runningSince).toBe(1000)
    applyConversationEvent(state, makeEvent('turn.started', { started_at: 1200 }, 2))
    expect(state.runningSince).toBe(1200)
  })

  it('voltar a ocioso, fechar ou falhar limpa o início; esperar uma decisão não', () => {
    const state = emptyConversation('s1')
    applyConversationEvent(state, makeEvent('turn.started', { started_at: 1000 }, 1))
    applyConversationEvent(state, makeEvent('session.state', { state: 'running', error: null }, 2))
    applyConversationEvent(state, makeEvent('session.state', { state: 'awaiting_decision', error: null }, 3))
    expect(state.runningSince).toBe(1000)
    applyConversationEvent(state, makeEvent('session.state', { state: 'idle', error: null }, 4))
    expect(state.runningSince).toBeNull()
    applyConversationEvent(state, makeEvent('turn.started', { started_at: 2000 }, 5))
    applyConversationEvent(state, makeEvent('session.state', { state: 'error', error: 'caiu' }, 6))
    expect(state.runningSince).toBeNull()
  })

  it('o estado "rodando" sozinho não inventa um início', () => {
    const state = emptyConversation('s1')
    applyConversationEvent(state, makeEvent('session.state', { state: 'running', error: null }, 1))
    expect(state.runningSince).toBeNull()
  })

  it('o snapshot traz o início do turno aberto, mesmo o aberto pelo agente', () => {
    // A última mensagem do usuário é bem anterior: o início vem do backend, não dela.
    const items = [{ type: 'user', id: 'u1', text: 'oi', at: 100 }]
    const conv = conversationFromSnapshot(makeSnapshot({ state: 'running', items: items as never, turn_started_at: 9000 }))
    expect(conv.runningSince).toBe(9000)
  })

  it('snapshot sem início (ocioso ou backend sem o dado) deixa o início vazio', () => {
    const items = [{ type: 'user', id: 'u1', text: 'oi', at: 100 }]
    expect(conversationFromSnapshot(makeSnapshot({ state: 'idle' })).runningSince).toBeNull()
    expect(conversationFromSnapshot(makeSnapshot({ state: 'running', items: items as never })).runningSince).toBeNull()
  })

  it('recarregar o snapshot no meio do turno usa o início do novo snapshot', async () => {
    const store = useConversationStore()
    let started = 40
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/sessions/s1': () => jsonResponse(makeSnapshot({ seq: 1, state: 'running', turn_started_at: started })) }))
    await store.load('s1')
    expect(store.get('s1')!.runningSince).toBe(40)
    // Um turno novo começou enquanto o WebSocket estava fora: não herda o início do anterior.
    started = 90
    await store.load('s1')
    expect(store.get('s1')!.runningSince).toBe(90)
  })
})
