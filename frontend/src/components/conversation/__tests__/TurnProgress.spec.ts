import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import { createAppRouter } from '../../../router'
import { jsonResponse, makeEvent, makeProject, makeSnapshot, routeFetch } from '../../../test/factories'
import { useProjectsStore } from '../../../stores/projects'
import { useGitStore } from '../../../stores/git'

const fake = vi.hoisted(() => ({ session: new Map<string, (e: unknown) => void>() }))
vi.mock('../../../api/socket', () => ({
  useEventSocket: () => ({
    onSession: (id: string, h: (e: unknown) => void) => { fake.session.set(id, h); return () => fake.session.delete(id) },
    onReconnect: () => () => {},
    onOpen: () => () => {},
  }),
}))

import ConversationThread from '../ConversationThread.vue'

enableAutoUnmount(afterEach)
let pinia: Pinia
// Frozen at a whole second so "17 s" is exact; timers stay real.
const NOW = Date.parse('2026-10-19T12:00:00Z')
beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(NOW)
  pinia = createPinia()
  setActivePinia(pinia)
  fake.session.clear()
  const projects = useProjectsStore(pinia)
  projects.projects = [makeProject({ id: 1 })]
  projects.loaded = true
  useGitStore(pinia).set(1, [])
})
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

const seconds = NOW / 1000
const user = (id: string, at: number | null = seconds - 600) => ({ type: 'user', id, text: id, at })
// The backend says when the open turn began; the user message's own time plays no part.
const started = { turn_started_at: seconds - 17 }
const tool = (id: string, name: string, extra: Record<string, unknown> = {}) => ({
  type: 'tool', id, tool_use_id: `tu-${id}`, name, input: { file_path: `/p/${id}.py` },
  result: { content: 'ok', is_error: false, details: null }, streaming: false, parent_tool_use_id: null, ...extra,
})
const todos = (id: string, ...items: [string, string][]) =>
  tool(id, 'TodoWrite', { input: { todos: items.map(([content, status]) => ({ content, status })) } })
const text = (id: string, streaming = false) => ({ type: 'text', id, text: `texto ${id}`, streaming, parent_tool_use_id: null })
const prompt = (toolUseId: string) => ({ prompt_id: 'p1', tool_name: 'Bash', input: { command: 'ls' }, can_always: true, tool_use_id: toolUseId })

async function mountWith(snapshot: Record<string, unknown>) {
  vi.stubGlobal('fetch', routeFetch({ 'GET /api/sessions/s1': () => jsonResponse(makeSnapshot({ seq: 1, ...snapshot })) }))
  const router = createAppRouter(createMemoryHistory())
  await router.push('/sessions/s1')
  const w = mount(ConversationThread, { props: { id: 's1', visible: true }, global: { plugins: [pinia, router] }, attachTo: document.body })
  await flushPromises()
  return w
}
type Wrapper = Awaited<ReturnType<typeof mountWith>>
const live = (w: Wrapper) => w.find('[data-test="turn-live"]')
const cards = (w: Wrapper) => w.findAll('[data-test="turn-tasks"]')
const send = async (event: ReturnType<typeof makeEvent>) => {
  fake.session.get('s1')!(event)
  await flushPromises()
}

describe('lista de tarefas no pé do turno em andamento', () => {
  const items = [user('u1'), todos('t1', ['Ler o código', 'completed'], ['Escrever o teste', 'in_progress'], ['Rodar tudo', 'pending'])]

  it('aparece depois da última entrada do trilho, com uma linha por tarefa', async () => {
    const w = await mountWith({ state: 'running', items: [...items, text('a')] })
    const card = cards(w)[0]!
    expect(card.findAll('[data-test="turn-task-label"]').map((r) => r.text())).toEqual(['Ler o código', 'Escrever o teste', 'Rodar tudo'])
    const entries = w.findAll('[data-test="turn-entry"]')
    const rail = entries[entries.length - 1]!.element
    expect(rail.compareDocumentPosition(card.element) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    for (const cls of ['rounded-lg', 'border', 'border-line', 'bg-panel', 'px-3', 'py-2']) expect(card.classes()).toContain(cls)
  })

  it('marca concluída (✓ verde), em andamento (laranja girando) e pendente (tracejado cinza)', async () => {
    const w = await mountWith({ state: 'running', items })
    const [done, doing, pending] = w.findAll('[data-test="turn-task"]')
    expect(done!.attributes('data-status')).toBe('completed')
    expect(done!.find('[data-test="turn-task-mark"]').classes()).toContain('text-primary')
    expect(done!.find('[data-test="turn-task-label"]').classes()).toContain('text-fg-muted')

    expect(doing!.attributes('data-status')).toBe('in_progress')
    const spinner = doing!.find('[data-test="turn-task-mark"]')
    expect(spinner.classes()).toEqual(expect.arrayContaining(['text-secondary', 'animate-spin', 'motion-reduce:animate-none']))
    expect(doing!.find('[data-test="turn-task-label"]').classes()).toEqual(expect.arrayContaining(['text-fg', 'font-medium']))

    expect(pending!.attributes('data-status')).toBe('pending')
    const mark = pending!.find('[data-test="turn-task-mark"]')
    expect(mark.classes()).toContain('text-fg-subtle')
    expect(mark.classes()).not.toContain('animate-spin')
    expect(mark.find('circle').attributes('stroke-dasharray')).toBeTruthy()
  })

  it('é atualizada no lugar quando a lista muda', async () => {
    const w = await mountWith({ state: 'running', items })
    await send(makeEvent('item.upsert', todos('t1', ['Ler o código', 'completed'], ['Escrever o teste', 'completed'], ['Rodar tudo', 'in_progress']), 2))
    expect(cards(w)).toHaveLength(1)
    expect(w.findAll('[data-test="turn-task"]').map((r) => r.attributes('data-status'))).toEqual(['completed', 'completed', 'in_progress'])
  })

  it('o cartão nasce quando a primeira lista é criada', async () => {
    const w = await mountWith({ state: 'running', items: [user('u1')] })
    expect(cards(w)).toHaveLength(0)
    await send(makeEvent('item.upsert', todos('t1', ['Uma', 'pending']), 2))
    expect(cards(w)).toHaveLength(1)
  })

  it('não aparece sem nenhuma tarefa na sessão', async () => {
    const w = await mountWith({ state: 'running', items: [user('u1'), text('a')] })
    expect(cards(w)).toHaveLength(0)
    expect(live(w).exists()).toBe(true)
  })

  it('mostra a lista vigente de turno anterior enquanto houver tarefa não concluída', async () => {
    const w = await mountWith({ state: 'running', items: [...items, user('u2'), text('a')] })
    expect(cards(w)).toHaveLength(2)
    const [old, current] = cards(w)
    expect(old!.attributes('data-muted')).toBe('true')
    expect(current!.attributes('data-muted')).toBeUndefined()
    expect(current!.findAll('[data-test="turn-task"]')).toHaveLength(3)
  })

  it('tudo concluído e o turno atual não mexeu: não mostra no turno em andamento', async () => {
    const w = await mountWith({
      state: 'running',
      items: [user('u1'), todos('t1', ['A', 'completed'], ['B', 'completed']), user('u2'), text('a')],
    })
    // Só o turno que mexeu na lista, já terminado, a mostra.
    expect(cards(w)).toHaveLength(1)
    expect(cards(w)[0]!.attributes('data-muted')).toBe('true')
    expect(w.findAll('[data-test="turn"]')[1]!.find('[data-test="turn-tasks"]').exists()).toBe(false)
  })

  it('o cartão antes da linha viva', async () => {
    const w = await mountWith({ state: 'running', items })
    const card = cards(w)[0]!.element
    expect(card.compareDocumentPosition(live(w).element) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })
})

describe('turno terminado', () => {
  const items = [user('u1'), todos('t1', ['Ler', 'completed'], ['Escrever', 'in_progress'])]

  it('a lista fica em tom apagado, sem animação, acima do "Concluído"', async () => {
    const w = await mountWith({ state: 'idle', items })
    const card = cards(w)[0]!
    expect(card.attributes('data-muted')).toBe('true')
    expect(card.classes()).toContain('opacity-70')
    expect(card.find('.animate-spin').exists()).toBe(false)
    expect(card.findAll('[data-test="turn-task"]')).toHaveLength(2)
    const end = w.find('[data-test="turn-end"]')
    expect(card.element.compareDocumentPosition(end.element) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(end.text()).toContain('Concluído')
  })

  it('a linha viva some', async () => {
    const w = await mountWith({ state: 'idle', items })
    expect(live(w).exists()).toBe(false)
  })

  it('cada turno mostra a lista como estava ao fim dele, só se mexeu nela', async () => {
    const w = await mountWith({
      state: 'idle',
      items: [
        user('u1'), todos('t1', ['A', 'in_progress'], ['B', 'pending']),
        user('u2'), text('x'),
        user('u3'), todos('t2', ['A', 'completed'], ['B', 'completed']),
      ],
    })
    const turns = w.findAll('[data-test="turn"]')
    expect(turns[0]!.findAll('[data-test="turn-task"]').map((r) => r.attributes('data-status'))).toEqual(['in_progress', 'pending'])
    expect(turns[1]!.find('[data-test="turn-tasks"]').exists()).toBe(false)
    expect(turns[2]!.findAll('[data-test="turn-task"]').map((r) => r.attributes('data-status'))).toEqual(['completed', 'completed'])
  })

  it('ao terminar o turno, o cartão vivo vira o apagado e a linha viva some', async () => {
    const w = await mountWith({ state: 'running', items, turn_output_tokens: 300 })
    expect(live(w).exists()).toBe(true)
    expect(cards(w)[0]!.attributes('data-muted')).toBeUndefined()
    await send(makeEvent('session.state', { state: 'idle', error: null }, 2))
    expect(live(w).exists()).toBe(false)
    expect(cards(w)[0]!.attributes('data-muted')).toBe('true')
    expect(cards(w)[0]!.find('.animate-spin').exists()).toBe(false)
  })

  it('as ferramentas de tarefa não aparecem no trilho: o cartão do pé é o registro', async () => {
    const w = await mountWith({ state: 'idle', items })
    expect(w.find('[data-test="task-tool"]').exists()).toBe(false)
    expect(w.findAll('[data-test="turn-entry"]')).toHaveLength(0)
    expect(cards(w)).toHaveLength(1)
  })

  it('um turno só com chamadas de tarefa não deixa trilho vazio', async () => {
    const w = await mountWith({ state: 'idle', items })
    expect(w.find('[data-test="turn"]').find('.bg-line').exists()).toBe(false)
    expect(w.find('[data-test="turn-end"]').exists()).toBe(true)
  })

  it('cada atualização da lista não vira uma linha no trilho', async () => {
    const w = await mountWith({
      state: 'running',
      items: [user('u1'), tool('c1', 'TaskCreate', { input: { subject: 'Uma' }, result: { content: 'Task #1 created successfully', is_error: false, details: null } }), tool('u', 'TaskUpdate', { input: { taskId: '1', status: 'in_progress' } })],
    })
    expect(w.findAll('[data-test="turn-entry"]')).toHaveLength(0)
    expect(w.find('[data-test="task-tool"]').exists()).toBe(false)
    expect(w.findAll('[data-test="turn-task"]').map((r) => r.attributes('data-status'))).toEqual(['in_progress'])
  })

  it('a lista de tarefas de um subagente não entra no cartão do pé do turno', async () => {
    const inner = tool('in', 'TodoWrite', { input: { todos: [{ content: 'Do sub', status: 'pending' }] }, parent_tool_use_id: 'tu-ag' })
    const agent = tool('ag', 'Agent', { input: { subagent_type: 'reviewer', description: 'x' }, result: null,
      subagent: { task_id: 't', subagent_type: 'reviewer', description: 'x', status: 'running', last_activity: null, usage: null, summary: null } })
    const w = await mountWith({ state: 'running', items: [user('u1'), agent, inner] })
    // O cartão do subagente fica no bloco recolhido; o do pé do turno vem só do agente principal.
    expect(cards(w)).toHaveLength(0)
  })
})

describe('linha viva', () => {
  const base = [user('u1')]

  it('três pontinhos pulsando em secundária, o que acontece, o tempo e os tokens', async () => {
    const w = await mountWith({ state: 'running', items: base, turn_output_tokens: 1600, ...started })
    const line = live(w)
    expect(line.text().replace(/\s+/g, ' ')).toBe('Pensando · 17 s · 1,6 mil tokens')
    const dots = line.findAll('[data-test="turn-live-dot"]')
    expect(dots).toHaveLength(3)
    for (const dot of dots) {
      expect(dot.classes()).toEqual(expect.arrayContaining(['bg-secondary', 'animate-pulse', 'motion-reduce:animate-none']))
      expect(dot.attributes('aria-hidden')).toBe('true')
    }
    expect(line.classes()).toEqual(expect.arrayContaining(['font-mono', 'text-[0.6875rem]']))
    expect(line.find('[data-test="turn-live-activity"]').classes()).toContain('text-secondary-soft')
    expect(line.find('[data-test="turn-live-meta"]').classes()).toContain('text-fg-subtle')
  })

  it('omite o pedaço dos tokens enquanto o número não é conhecido', async () => {
    const w = await mountWith({ state: 'running', items: base, ...started })
    expect(live(w).text().replace(/\s+/g, ' ')).toBe('Pensando · 17 s')
  })

  it('os tokens acompanham o evento turn.tokens', async () => {
    const w = await mountWith({ state: 'running', items: base })
    await send(makeEvent('turn.tokens', { output_tokens: 353 }, 2))
    expect(live(w).text()).toContain('353 tokens')
    await send(makeEvent('turn.tokens', { output_tokens: 1600 }, 3))
    expect(live(w).text()).toContain('1,6 mil tokens')
  })

  it('"Escrevendo" com texto em streaming', async () => {
    const w = await mountWith({ state: 'running', items: [...base, text('a', true)] })
    expect(live(w).find('[data-test="turn-live-activity"]').text()).toBe('Escrevendo')
  })

  it('a ação em execução, como no bloco recolhido', async () => {
    const running = tool('b', 'Bash', { input: { command: 'pnpm test', description: 'Rodar os testes' }, result: null })
    const w = await mountWith({ state: 'running', items: [...base, running] })
    expect(live(w).find('[data-test="turn-live-activity"]').text()).toBe('Comando · Rodar os testes')
  })

  it('"esperando você" com pedido pendente', async () => {
    const running = tool('b', 'Bash', { input: { command: 'ls' }, result: null })
    const w = await mountWith({ state: 'awaiting_decision', items: [...base, running], prompts: [prompt('tu-b')] })
    expect(live(w).find('[data-test="turn-live-activity"]').text()).toBe('esperando você')
  })

  it('sem o início do turno a linha omite o tempo, sem inventar um', async () => {
    const w = await mountWith({ state: 'running', items: [user('u1', seconds - 600)] })
    expect(live(w).text().replace(/\s+/g, ' ')).toBe('Pensando')
  })

  it('turno aberto pelo agente ao recarregar: conta desde o início do backend, não da última mensagem', async () => {
    const w = await mountWith({ state: 'running', items: [user('u1', seconds - 600), text('a')], turn_started_at: seconds - 5 })
    expect(live(w).text()).toContain('5 s')
    expect(live(w).text()).not.toContain('min')
  })

  it('turn.started de um turno novo reinicia o tempo', async () => {
    const w = await mountWith({ state: 'running', items: base, ...started })
    expect(live(w).text()).toContain('17 s')
    vi.setSystemTime(NOW + 3000)
    await send(makeEvent('turn.started', { started_at: seconds + 3 }, 2))
    expect(live(w).text()).toContain('0 s')
  })

  it('só o último turno tem linha viva', async () => {
    const w = await mountWith({ state: 'running', items: [user('u1'), text('a'), user('u2')] })
    expect(w.findAll('[data-test="turn-live"]')).toHaveLength(1)
    expect(w.findAll('[data-test="turn"]')[1]!.find('[data-test="turn-live"]').exists()).toBe(true)
  })

  it('sessão ociosa não tem linha viva', async () => {
    const w = await mountWith({ state: 'idle', items: base })
    expect(live(w).exists()).toBe(false)
  })
})
