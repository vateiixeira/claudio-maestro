import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import { createAppRouter } from '../../../router'
import { jsonResponse, makeEvent, makeProject, makeSnapshot, routeFetch } from '../../../test/factories'
import { useProjectsStore } from '../../../stores/projects'
import { useConversationStore } from '../../../stores/conversation'
import { useChangesPanelStore } from '../../../stores/changesPanel'
import type { WsEvent } from '../../../types/events'

const fake = vi.hoisted(() => ({
  session: new Map<string, (e: unknown) => void>(),
  reconnect: new Set<() => void>(),
}))
vi.mock('../../../api/socket', () => ({
  useEventSocket: () => ({
    onSession: (id: string, h: (e: unknown) => void) => { fake.session.set(id, h); return () => fake.session.delete(id) },
    onReconnect: (h: () => void) => { fake.reconnect.add(h); return () => fake.reconnect.delete(h) },
    onOpen: (h: () => void) => { fake.reconnect.add(h); return () => fake.reconnect.delete(h) },
  }),
}))

import ConversationThread from '../ConversationThread.vue'

enableAutoUnmount(afterEach)
let pinia: Pinia

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  fake.session.clear()
  fake.reconnect.clear()
  const projects = useProjectsStore(pinia)
  projects.projects = [makeProject({ id: 1, name: 'loja-online' })]
  projects.loaded = true
})
afterEach(() => vi.unstubAllGlobals())

const text = (id: string, t: string) => ({ type: 'text', id, text: t, streaming: false, parent_tool_use_id: null })

async function mountView(props: Record<string, unknown> = {}) {
  const router = createAppRouter(createMemoryHistory())
  await router.push('/sessions/s1')
  const w = mount(ConversationThread, { props: { id: 's1', visible: true, ...props }, global: { plugins: [pinia, router] } })
  await flushPromises()
  return w
}

describe('corpo da conversa', () => {
  it('carrega o retrato e mostra os itens e o compositor', async () => {
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/sessions/s1': () => jsonResponse(makeSnapshot({ state: 'idle', seq: 2, items: [text('a', 'Olá do retrato') as never] })),
    }))
    const w = await mountView()
    expect(w.text()).toContain('Olá do retrato')
    expect(w.find('textarea').exists()).toBe(true)
    expect(w.find('[data-test="interrupt"]').exists()).toBe(false)
  })

  it('avisa quando a conversa não existe (404)', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/sessions/s1': () => jsonResponse({ detail: 'Sessão não encontrada.' }, 404) }))
    const w = await mountView()
    expect(w.emitted('missing')).toHaveLength(1)
  })

  it('aplica eventos do socket, mostra "Interromper" rodando e cartão de permissão', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/sessions/s1': () => jsonResponse(makeSnapshot({ seq: 1 })) }))
    const w = await mountView()
    const emit = (e: WsEvent) => fake.session.get('s1')!(e)
    emit(makeEvent('item.upsert', text('b', 'Novo texto'), 2))
    emit(makeEvent('session.state', { state: 'running', error: null }, 3))
    emit(makeEvent('prompt.request', { prompt_id: 'p1', tool_name: 'Bash', input: { command: 'ls' }, can_always: false }, 4))
    emit(makeEvent('turn.result', { subtype: 'success', is_error: false, duration_ms: 1500, total_cost_usd: 0.0123 }, 5))
    await flushPromises()
    expect(w.text()).toContain('Novo texto')
    expect(w.find('[data-test="interrupt"]').exists()).toBe(true)
    expect(w.find('[data-test="permission-card"]').exists()).toBe(true)
    emit(makeEvent('prompt.resolved', { prompt_id: 'p1', decision: 'allow_once' }, 6))
    await flushPromises()
    expect(w.find('[data-test="permission-card"]').exists()).toBe(false)
    emit(makeEvent('session.state', { state: 'idle', error: null }, 7))
    await flushPromises()
    expect(w.find('[data-test="turn-end"]').text()).toContain('1,5 s')
  })

  it('mostra o erro da sessão acima do campo', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/sessions/s1': () => jsonResponse(makeSnapshot({ state: 'error', error: 'O processo caiu.' })) }))
    const w = await mountView()
    expect(w.find('[data-test="session-error"]').text()).toContain('O processo caiu.')
  })

  it('recarrega o retrato ao reconectar', async () => {
    let calls = 0
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/sessions/s1': () => {
        calls++
        return jsonResponse(makeSnapshot({ seq: calls, items: calls > 1 ? [text('z', 'Depois da queda') as never] : [] }))
      },
    }))
    const w = await mountView()
    fake.reconnect.forEach((h) => h())
    await flushPromises()
    expect(calls).toBe(2)
    expect(w.text()).toContain('Depois da queda')
  })

  it('mostra o erro ao carregar', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/sessions/s1': () => jsonResponse({ detail: 'Servidor caiu.' }, 500) }))
    const w = await mountView()
    expect(w.find('[role="alert"]').text()).toContain('Servidor caiu.')
    expect(w.emitted('missing')).toBeUndefined()
  })

  it('depois de uma falha de carga oferece "Tentar de novo", que busca o retrato outra vez', async () => {
    let calls = 0
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/sessions/s1': () => {
        calls++
        return calls === 1 ? jsonResponse({ detail: 'Servidor caiu.' }, 500) : jsonResponse(makeSnapshot({ seq: 1, items: [text('a', 'Voltou') as never] }))
      },
    }))
    const w = await mountView()
    const retry = w.find('[data-test="retry-load"]')
    expect(retry.element.tagName).toBe('BUTTON')
    expect(retry.text()).toBe('Tentar de novo')
    await retry.trigger('click')
    await flushPromises()
    expect(calls).toBe(2)
    expect(w.find('[data-test="retry-load"]').exists()).toBe(false)
    expect(w.text()).toContain('Voltou')
  })

  it('"Tentar de novo" fica desabilitado enquanto recarrega e volta a habilitar se falhar de novo', async () => {
    const pending: Array<(r: Response) => void> = []
    let calls = 0
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/sessions/s1': () => {
        calls++
        if (calls === 1) return jsonResponse({ detail: 'Servidor caiu.' }, 500)
        return new Promise<Response>((resolve) => pending.push(resolve)) as never
      },
    }))
    const w = await mountView()
    const retry = () => w.find('[data-test="retry-load"]')
    expect(retry().attributes('disabled')).toBeUndefined()
    await retry().trigger('click')
    await flushPromises()
    expect(calls).toBe(2)
    expect(retry().exists()).toBe(true)
    expect(retry().attributes('disabled')).toBeDefined()
    // A second click while reloading does not start another request.
    await retry().trigger('click')
    expect(calls).toBe(2)
    pending[0]!(jsonResponse({ detail: 'Ainda fora.' }, 500))
    await flushPromises()
    expect(w.find('[role="alert"]').text()).toContain('Ainda fora.')
    expect(retry().attributes('disabled')).toBeUndefined()
  })

  it('sair da conversa antes do retrato chegar não a devolve ao store nem marca como vista', async () => {
    vi.useFakeTimers()
    try {
      const pending: Array<(r: Response) => void> = []
      const fetchMock = routeFetch({
        'GET /api/sessions/s1': () => new Promise<Response>((resolve) => pending.push(resolve)) as never,
        'POST /api/sessions/s1/seen': () => jsonResponse(undefined, 204),
      })
      vi.stubGlobal('fetch', fetchMock)
      const router = createAppRouter(createMemoryHistory())
      await router.push('/sessions/s1')
      const w = mount(ConversationThread, { props: { id: 's1', visible: true }, global: { plugins: [pinia, router] } })
      await flushPromises()
      w.unmount()
      pending[0]!(jsonResponse(makeSnapshot({ seq: 1 })))
      await flushPromises()
      await vi.advanceTimersByTimeAsync(1000)
      expect(useConversationStore(pinia).get('s1')).toBeUndefined()
      expect(fetchMock).not.toHaveBeenCalledWith('/api/sessions/s1/seen', expect.anything())
    } finally {
      vi.useRealTimers()
    }
  })

  it('marca como vista ao receber foco e ao chegar item novo, só se visível', async () => {
    vi.useFakeTimers()
    const fetchMock = routeFetch({
      'GET /api/sessions/s1': () => jsonResponse(makeSnapshot({ seq: 1 })),
      'POST /api/sessions/s1/seen': () => jsonResponse(undefined, 204),
    })
    vi.stubGlobal('fetch', fetchMock)
    const w = await mountView()
    const seen = () => fetchMock.mock.calls.filter(([url]) => url === '/api/sessions/s1/seen').length
    await vi.advanceTimersByTimeAsync(1000)
    const afterLoad = seen()
    expect(afterLoad).toBe(1)

    await w.find('[data-test="conversation-scroller"]').trigger('focusin')
    await vi.advanceTimersByTimeAsync(1000)
    expect(seen()).toBe(afterLoad + 1)

    fake.session.get('s1')!(makeEvent('item.upsert', text('n', 'novo'), 2))
    await vi.advanceTimersByTimeAsync(1000)
    expect(seen()).toBe(afterLoad + 2)

    await w.setProps({ visible: false })
    fake.session.get('s1')!(makeEvent('item.upsert', text('m', 'outro'), 3))
    await w.find('[data-test="conversation-scroller"]').trigger('focusin')
    await vi.advanceTimersByTimeAsync(1000)
    expect(seen()).toBe(afterLoad + 2)
    vi.useRealTimers()
  })

  it('cancela as assinaturas do socket ao trocar de sessão e no unmount', async () => {
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/sessions/s1': () => jsonResponse(makeSnapshot()),
      'GET /api/sessions/s2': () => jsonResponse(makeSnapshot({ session_id: 's2' })),
    }))
    const w = await mountView()
    expect([...fake.session.keys()]).toEqual(['s1'])
    expect(fake.reconnect.size).toBe(1)
    await w.setProps({ id: 's2' })
    await flushPromises()
    expect([...fake.session.keys()]).toEqual(['s2'])
    expect(fake.reconnect.size).toBe(1)
    w.unmount()
    expect(fake.session.size).toBe(0)
    expect(fake.reconnect.size).toBe(0)
  })

  it('o rascunho não vaza de uma sessão para outra', async () => {
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/sessions/s1': () => jsonResponse(makeSnapshot()),
      'GET /api/sessions/s2': () => jsonResponse(makeSnapshot({ session_id: 's2' })),
    }))
    const w = await mountView()
    await w.find('textarea').setValue('rascunho da A')
    await w.setProps({ id: 's2' })
    await flushPromises()
    expect((w.find('textarea').element as HTMLTextAreaElement).value).toBe('')
  })

  it('não marca como vista se a conversa deixa de estar visível antes do atraso', async () => {
    vi.useFakeTimers()
    const fetchMock = routeFetch({
      'GET /api/sessions/s1': () => jsonResponse(makeSnapshot()),
      'POST /api/sessions/s1/seen': () => jsonResponse(undefined, 204),
    })
    vi.stubGlobal('fetch', fetchMock)
    const seen = () => fetchMock.mock.calls.filter(([url]) => url === '/api/sessions/s1/seen').length
    const w = await mountView({ visible: false })
    await vi.advanceTimersByTimeAsync(1000)
    expect(seen()).toBe(0)
    await w.setProps({ visible: true })
    await w.setProps({ visible: false })
    await vi.advanceTimersByTimeAsync(1000)
    expect(seen()).toBe(0)
    vi.useRealTimers()
  })

  it('recheca a aba oculta quando o atraso termina', async () => {
    vi.useFakeTimers()
    const fetchMock = routeFetch({
      'GET /api/sessions/s1': () => jsonResponse(makeSnapshot()),
      'POST /api/sessions/s1/seen': () => jsonResponse(undefined, 204),
    })
    vi.stubGlobal('fetch', fetchMock)
    await mountView()
    const spy = vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden')
    await vi.advanceTimersByTimeAsync(1000)
    spy.mockRestore()
    expect(fetchMock.mock.calls.filter(([url]) => url === '/api/sessions/s1/seen')).toHaveLength(0)
    vi.useRealTimers()
  })

  it('marca como vista quando o turno termina sem item novo', async () => {
    vi.useFakeTimers()
    const fetchMock = routeFetch({
      'GET /api/sessions/s1': () => jsonResponse(makeSnapshot({ seq: 1, items: [text('a', 'x') as never] })),
      'POST /api/sessions/s1/seen': () => jsonResponse(undefined, 204),
    })
    vi.stubGlobal('fetch', fetchMock)
    await mountView()
    const seen = () => fetchMock.mock.calls.filter(([url]) => url === '/api/sessions/s1/seen').length
    await vi.advanceTimersByTimeAsync(1000)
    const before = seen()
    fake.session.get('s1')!(makeEvent('item.upsert', text('a', 'x final'), 2))
    fake.session.get('s1')!(makeEvent('turn.result', { subtype: 'success', is_error: false, duration_ms: 1, total_cost_usd: 0 }, 3))
    await vi.advanceTimersByTimeAsync(1000)
    expect(seen()).toBe(before + 1)
    vi.useRealTimers()
  })

  it('mostra a faixa de histórico cortado', async () => {
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/sessions/s1': () => jsonResponse(makeSnapshot({ history_truncated: true, items: [text('a', 'x') as never] } as never)),
    }))
    const w = await mountView()
    expect(w.find('[data-test="history-truncated"]').text()).toBe('Mostrando as mensagens mais recentes.')
  })

})

describe('ao sair da conversa', () => {
  const editItem = {
    type: 'tool', id: 'e1', tool_use_id: 'e1', name: 'Edit', input: { file_path: '/p/a.ts' },
    result: null, streaming: false, parent_tool_use_id: null,
  } as never
  const result = (ms: number, seq: number) => makeEvent('turn.result', { subtype: 'success', is_error: false, duration_ms: ms, total_cost_usd: 0 }, seq)

  it('esquece a conversa ao desmontar: a volta não herda o último resultado', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/sessions/s1': () => jsonResponse(makeSnapshot({ seq: 1 })) }))
    const conversations = useConversationStore(pinia)
    const first = await mountView()
    fake.session.get('s1')!(result(1500, 2))
    await flushPromises()
    expect(conversations.get('s1')?.lastResult?.duration_ms).toBe(1500)

    first.unmount()
    expect(conversations.get('s1')).toBeUndefined()
    expect(fake.session.has('s1')).toBe(false)

    const second = await mountView()
    expect(conversations.get('s1')?.lastResult).toBeNull()
    expect(second.text()).not.toContain('1,5 s')
  })

  it('fecha o painel de alterações que era desta conversa ao desmontar', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/sessions/s1': () => jsonResponse(makeSnapshot({ seq: 1 })) }))
    const panel = useChangesPanelStore(pinia)
    const w = await mountView()
    panel.open('s1', editItem)
    w.unmount()
    expect(panel.sessionId).toBeNull()
    expect(panel.edit).toBeNull()
  })

  it('deixa em paz o painel de outra conversa', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/sessions/s1': () => jsonResponse(makeSnapshot({ seq: 1 })) }))
    const panel = useChangesPanelStore(pinia)
    const w = await mountView()
    panel.open('outra', editItem)
    w.unmount()
    expect(panel.sessionId).toBe('outra')
  })

  it('ao trocar o id esquece a conversa anterior e fecha o painel dela', async () => {
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/sessions/s1': () => jsonResponse(makeSnapshot({ seq: 1 })),
      'GET /api/sessions/s2': () => jsonResponse(makeSnapshot({ session_id: 's2', seq: 1 })),
    }))
    const conversations = useConversationStore(pinia)
    const panel = useChangesPanelStore(pinia)
    const w = await mountView()
    panel.open('s1', editItem)
    await w.setProps({ id: 's2' })
    await flushPromises()

    expect(conversations.get('s1')).toBeUndefined()
    expect(conversations.get('s2')).toBeDefined()
    expect(panel.sessionId).toBeNull()
    expect(fake.session.has('s1')).toBe(false)
  })
})

describe('controles e imagens na conversa', () => {
  it('mostra os seletores e aceita imagem arrastada para a conversa', async () => {
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/sessions/s1': () => jsonResponse({ ...makeSnapshot({ seq: 1 }), model: null, effort: null, permission_mode: 'default' }),
      'GET /api/models': () => jsonResponse([{ value: 'default', displayName: 'Padrão', description: '', supportsEffort: false }]),
    }))
    const w = await mountView()
    expect(w.find('button[aria-label="Modelo: Padrão"]').exists()).toBe(true)
    expect(w.find('button[aria-label="Modo: pede permissão"]').exists()).toBe(true)
    const file = new File([new Uint8Array([65, 65, 65])], 'col.png', { type: 'image/png' })
    await w.find('[data-test="conversation-scroller"]').trigger('drop', { dataTransfer: { files: [file], types: ['Files'] } })
    await flushPromises()
    await new Promise((r) => setTimeout(r, 0))
    await flushPromises()
    expect(w.find('[data-test="attachment-draft"]').text()).toContain('col.png')
  })

  describe('prompts e árvore de itens', () => {
    const toolItem = (id: string, name: string, parent: string | null, extra: Record<string, unknown> = {}) => ({
      type: 'tool', id, tool_use_id: `tu-${id}`, name, input: { file_path: `/p/${id}.py`, description: `desc ${id}` },
      result: null, streaming: false, parent_tool_use_id: parent, ...extra,
    })
    const agent = (id: string, parent: string | null) => toolItem(id, 'Agent', parent, {
      subagent: { task_id: id, subagent_type: 'Explore', description: `agente ${id}`, status: 'running', last_activity: null, usage: null, summary: null },
    })
    const load = (items: unknown[], prompts: unknown[] = []) =>
      vi.stubGlobal('fetch', routeFetch({ 'GET /api/sessions/s1': () => jsonResponse(makeSnapshot({ seq: 1, state: 'running', items: items as never, prompts: prompts as never })) }))

    it('escolhe o cartão pelo kind', async () => {
      load([], [
        { prompt_id: 'q', kind: 'question', tool_name: 'AskUserQuestion', input: {}, can_always: false, questions: [{ question: 'Q?', options: [{ label: 'A' }] }] },
        { prompt_id: 'pl', kind: 'plan', tool_name: 'ExitPlanMode', input: {}, can_always: false, plan: '# P' },
        { prompt_id: 't', kind: 'tool', tool_name: 'Bash', input: { command: 'ls' }, can_always: false },
      ])
      const w = await mountView()
      expect(w.findAll('[data-test="question-card"]')).toHaveLength(1)
      expect(w.findAll('[data-test="plan-card"]')).toHaveLength(1)
      expect(w.findAll('[data-test="permission-card"]')).toHaveLength(1)
    })

    it('filho cujo pai não chegou aparece no topo', async () => {
      load([toolItem('orfao', 'Read', 'tu-ausente')])
      const w = await mountView()
      expect(w.text()).toContain('/p/orfao.py')
    })

    it('subagente dentro de subagente aninha os filhos nos cartões', async () => {
      load([agent('a1', null), agent('a2', 'tu-a1'), toolItem('r', 'Read', 'tu-a2')])
      const w = await mountView()
      const outer = w.findAll('[data-test="subagent-card"]')
      expect(outer).toHaveLength(2)
      const inner = outer[0]!.find('[data-test="subagent-children"] [data-test="subagent-card"]')
      expect(inner.exists()).toBe(true)
      expect(inner.find('[data-test="subagent-children"]').text()).toContain('/p/r.py')
    })

    it('filho de ferramenta comum aparece recuado', async () => {
      load([toolItem('b', 'Bash', null), toolItem('c', 'Read', 'tu-b')])
      const w = await mountView()
      const indent = w.find('[data-test="tool-children"]')
      expect(indent.text()).toContain('/p/c.py')
    })

    it('pedido de permissão de um subagente aparece', async () => {
      load([agent('a1', null)], [{ prompt_id: 'p', tool_name: 'Bash', input: { command: 'rm x' }, can_always: false, tool_use_id: 'tu-sub' }])
      const w = await mountView()
      expect(w.find('[data-test="permission-card"]').text()).toContain('rm x')
    })
  })
})

describe('robustez da conversa', () => {
  it('envia mensagem durante um turno e com permissão pendente, e ela aparece na conversa', async () => {
    const bodies: string[] = []
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/sessions/s1': () => jsonResponse(makeSnapshot({ seq: 1, state: 'running' })),
      'POST /api/sessions/s1/messages': (init) => { bodies.push(init!.body as string); return jsonResponse({}, 202) },
    }))
    const w = await mountView()
    const emit = (e: WsEvent) => fake.session.get('s1')!(e)
    await w.find('textarea').setValue('primeira')
    expect(w.find('[data-test="send"]').attributes('disabled')).toBeUndefined()
    await w.find('[data-test="send"]').trigger('click')
    await flushPromises()
    emit(makeEvent('prompt.request', { prompt_id: 'p1', tool_name: 'Bash', input: { command: 'ls' }, can_always: false }, 2))
    emit(makeEvent('session.state', { state: 'awaiting_decision', error: null }, 3))
    await flushPromises()
    await w.find('textarea').setValue('segunda')
    await w.find('[data-test="send"]').trigger('click')
    await flushPromises()
    expect(bodies.map((b) => JSON.parse(b).text)).toEqual(['primeira', 'segunda'])
    emit(makeEvent('item.upsert', { type: 'user', id: 'u1', text: 'segunda', images: [], parent_tool_use_id: null }, 4))
    await flushPromises()
    expect(w.text()).toContain('segunda')
  })

  it('projeto com pasta apagada: aviso e envio desabilitado com explicação', async () => {
    useProjectsStore(pinia).projects = [makeProject({ id: 1, name: 'loja-online', available: false })]
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/sessions/s1': () => jsonResponse(makeSnapshot({ seq: 1 })) }))
    const w = await mountView()
    // A single notice, the one tied to the send button.
    expect(w.text().match(/pasta do projeto/g)).toHaveLength(1)
    expect(w.find('[data-test="send"]').attributes('aria-describedby')).toBe('blocked-s1')
    await w.find('textarea').setValue('oi')
    expect(w.find('[data-test="send"]').attributes('disabled')).toBeDefined()
  })
})

describe('acessibilidade da conversa', () => {
  it('anuncia só mensagens concluídas, não o texto em streaming', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/sessions/s1': () => jsonResponse(makeSnapshot({ seq: 1, state: 'running' })) }))
    const w = await mountView()
    const live = () => w.find('[data-test="conversation-live"]')
    expect(live().attributes('aria-live')).toBe('polite')
    const emit = (e: WsEvent) => fake.session.get('s1')!(e)
    emit(makeEvent('item.upsert', { type: 'text', id: 't1', text: 'Parcial', streaming: true, parent_tool_use_id: null }, 2))
    await flushPromises()
    expect(live().text()).toBe('')
    emit(makeEvent('item.upsert', { type: 'text', id: 't1', text: 'Resposta pronta', streaming: false, parent_tool_use_id: null }, 3))
    await flushPromises()
    expect(live().text()).toContain('Resposta pronta')
  })

  it('a área da conversa não é uma região viva (evita anunciar cada caractere)', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/sessions/s1': () => jsonResponse(makeSnapshot({ seq: 1 })) }))
    const w = await mountView()
    expect(w.find('[data-test="conversation-scroller"]').attributes('aria-live')).toBeUndefined()
  })
})
