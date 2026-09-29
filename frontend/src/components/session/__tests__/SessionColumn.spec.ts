import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import { createAppRouter } from '../../../router'
import { jsonResponse, makeEvent, makeProject, makeSnapshot, routeFetch } from '../../../test/factories'
import { useProjectsStore } from '../../../stores/projects'
import { useGitStore } from '../../../stores/git'
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

import SessionColumn from '../SessionColumn.vue'

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
  useGitStore(pinia).set(1, []) // branches already known: the column makes no git request
})
afterEach(() => vi.unstubAllGlobals())

const text = (id: string, t: string) => ({ type: 'text', id, text: t, streaming: false, parent_tool_use_id: null })

async function mountView(props: Record<string, unknown> = {}) {
  const router = createAppRouter(createMemoryHistory())
  await router.push('/sessions/s1')
  const w = mount(SessionColumn, { props: { id: 's1', visible: true, ...props }, global: { plugins: [pinia, router] } })
  await flushPromises()
  return w
}

describe('coluna da sessão', () => {
  it('cabeçalho sem git mostra "sem repositório git"', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/sessions/s1': () => jsonResponse(makeSnapshot({ seq: 1 })) }))
    const w = await mountView()
    expect(w.text()).toContain('sem repositório git')
  })

  it('carrega o retrato e mostra cabeçalho, itens e campo', async () => {
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/sessions/s1': () => jsonResponse(makeSnapshot({ title: 'Cupom expirado', state: 'idle', seq: 2, items: [text('a', 'Olá do retrato') as never] })),
    }))
    const w = await mountView()
    expect(w.find('h2').text()).toBe('Cupom expirado')
    expect(w.text()).toContain('loja-online')
    expect(w.find('[data-test="session-state"]').text()).toBe('Aguardando você')
    expect(w.text()).not.toContain('Parada')
    expect(w.text()).toContain('Olá do retrato')
    expect(w.find('textarea').exists()).toBe(true)
    expect(w.find('[data-test="interrupt"]').exists()).toBe(false)
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
    expect(w.find('[data-test="turn-footer"]').text()).toContain('1,5 s')
    emit(makeEvent('prompt.resolved', { prompt_id: 'p1', decision: 'allow_once' }, 6))
    await flushPromises()
    expect(w.find('[data-test="permission-card"]').exists()).toBe(false)
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

  it('avisa quando a sessão não existe mais (404)', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/sessions/s1': () => jsonResponse({ detail: 'Sessão não encontrada.' }, 404) }))
    const w = await mountView()
    expect(w.emitted('missing')).toHaveLength(1)
  })

  it('o botão de fechar emite close sem chamar o backend', async () => {
    const fetchMock = routeFetch({ 'GET /api/sessions/s1': () => jsonResponse(makeSnapshot()) })
    vi.stubGlobal('fetch', fetchMock)
    const w = await mountView()
    const before = fetchMock.mock.calls.length
    await w.find('button[aria-label="Fechar coluna"]').trigger('click')
    await flushPromises()
    expect(w.emitted('close')).toHaveLength(1)
    expect(fetchMock.mock.calls.length).toBe(before)
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

    await w.find('section').trigger('focusin')
    await vi.advanceTimersByTimeAsync(1000)
    expect(seen()).toBe(afterLoad + 1)

    fake.session.get('s1')!(makeEvent('item.upsert', text('n', 'novo'), 2))
    await vi.advanceTimersByTimeAsync(1000)
    expect(seen()).toBe(afterLoad + 2)

    await w.setProps({ visible: false })
    fake.session.get('s1')!(makeEvent('item.upsert', text('m', 'outro'), 3))
    await w.find('section').trigger('focusin')
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

  it('não marca como vista se a coluna deixa de estar visível antes do atraso', async () => {
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

  it('estado do cabeçalho usa rótulos visíveis e mantém erro e decisão', async () => {
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/sessions/s1': () => jsonResponse(makeSnapshot({ state: 'closed', seq: 1 })),
      'POST /api/sessions/s1/seen': () => jsonResponse(undefined, 204),
    }))
    const w = await mountView()
    const label = () => w.find('[data-test="session-state"]').text()
    expect(label()).toBe('Aguardando você')
    fake.session.get('s1')!(makeEvent('session.state', { state: 'running', error: null }, 2))
    await flushPromises()
    expect(label()).toBe('Em execução')
    fake.session.get('s1')!(makeEvent('session.state', { state: 'awaiting_decision', error: null }, 3))
    await flushPromises()
    expect(label()).toBe('Pede sua decisão')
    fake.session.get('s1')!(makeEvent('session.state', { state: 'error', error: 'x' }, 4))
    await flushPromises()
    expect(label()).toBe('Erro')
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

  it('avisa atividade externa vinda do retrato', async () => {
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/sessions/s1': () => jsonResponse(makeSnapshot({ external_activity: true } as never)),
    }))
    const w = await mountView()
    expect(w.find('[data-test="external-activity"]').text()).toContain('Esta sessão foi modificada fora do app no último minuto.')
  })

  it('avisa atividade externa vinda do envio', async () => {
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/sessions/s1': () => jsonResponse(makeSnapshot()),
      'POST /api/sessions/s1/messages': () => jsonResponse({ state: 'connecting', external_activity: true }),
    }))
    const w = await mountView()
    expect(w.find('[data-test="external-activity"]').exists()).toBe(false)
    await w.find('textarea').setValue('oi')
    await w.find('textarea').trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(w.find('[data-test="external-activity"]').text()).toContain('pode embaralhar o histórico')
  })

  it('mostra a faixa de histórico cortado', async () => {
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/sessions/s1': () => jsonResponse(makeSnapshot({ history_truncated: true, items: [text('a', 'x') as never] } as never)),
    }))
    const w = await mountView()
    expect(w.find('[data-test="history-truncated"]').text()).toBe('Mostrando as mensagens mais recentes.')
  })

  it('retrato posterior com external_activity false limpa o aviso', async () => {
    let external = true
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/sessions/s1': () => jsonResponse(makeSnapshot({ external_activity: external } as never)),
    }))
    const w = await mountView()
    expect(w.find('[data-test="external-activity"]').exists()).toBe(true)
    external = false
    fake.reconnect.forEach((h) => h())
    await flushPromises()
    expect(w.find('[data-test="external-activity"]').exists()).toBe(false)
  })

  it('o aviso externo some depois de 60 s', async () => {
    vi.useFakeTimers()
    try {
      vi.stubGlobal('fetch', routeFetch({
        'GET /api/sessions/s1': () => jsonResponse(makeSnapshot({ external_activity: true } as never)),
      }))
      const w = await mountView()
      expect(w.find('[data-test="external-activity"]').attributes('role')).toBe('status')
      await vi.advanceTimersByTimeAsync(59_000)
      expect(w.find('[data-test="external-activity"]').exists()).toBe(true)
      await vi.advanceTimersByTimeAsync(2_000)
      expect(w.find('[data-test="external-activity"]').exists()).toBe(false)
    } finally {
      vi.useRealTimers()
    }
  })
})

describe('controles e imagens na coluna', () => {
  it('mostra os seletores e aceita imagem arrastada para a coluna', async () => {
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/sessions/s1': () => jsonResponse({ ...makeSnapshot({ seq: 1 }), model: null, effort: null, permission_mode: 'default' }),
      'GET /api/models': () => jsonResponse([{ value: 'default', displayName: 'Padrão', description: '', supportsEffort: false }]),
    }))
    const w = await mountView()
    expect(w.find('button[aria-label="Modelo: Padrão"]').exists()).toBe(true)
    expect(w.find('button[aria-label="Modo: pede permissão"]').exists()).toBe(true)
    const file = new File([new Uint8Array([65, 65, 65])], 'col.png', { type: 'image/png' })
    await w.find('section').trigger('drop', { dataTransfer: { files: [file], types: ['Files'] } })
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

describe('robustez da coluna', () => {
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
    const notice = w.find('[data-test="project-unavailable"]')
    expect(notice.exists()).toBe(true)
    expect(notice.text()).toContain('pasta do projeto')
    await w.find('textarea').setValue('oi')
    expect(w.find('[data-test="send"]').attributes('disabled')).toBeDefined()
  })
})

})
