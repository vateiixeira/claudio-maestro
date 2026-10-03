import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { jsonResponse, makeSession, routeFetch } from '../../../test/factories'
import PlanStrip from '../PlanStrip.vue'
import Collapse from '../../Collapse.vue'
import type { PlanState, PlanSummary, Session } from '../../../types/api'

const summary = (extra: Partial<PlanSummary> = {}): PlanSummary => ({
  path: '/home/vi/dev/loja-online/docs/plan.md',
  title: 'Plano da loja',
  total: 12,
  done: 3,
  current: { number: 4, title: 'Faixa do plano' },
  ...extra,
})

const planState = (plan: PlanSummary): PlanState => ({
  link: 'auto',
  path: plan.path,
  plan,
  tasks: [
    { number: 1, title: 'Primeira', done: true },
    { number: 2, title: 'Segunda', done: true },
    { number: 3, title: 'Terceira', done: true },
    { number: 4, title: 'Faixa do plano', done: false },
    { number: 5, title: 'Quinta', done: false },
  ],
})

// 19 tasks: 14 done, the 15th is the current one and 4 are left after it.
const bigState = (): PlanState => {
  const plan = summary({ total: 19, done: 14, current: { number: 15, title: 'Quinze' } })
  return {
    link: 'auto',
    path: plan.path,
    plan,
    tasks: Array.from({ length: 19 }, (_, i) => ({ number: i + 1, title: i === 14 ? 'Quinze' : `Tarefa ${i + 1}`, done: i < 14 })),
  }
}
const bigSession = () => makeSession({ display_state: 'running', plan: bigState().plan })

const session = (extra: Partial<Session> = {}): Session =>
  makeSession({ display_state: 'running', plan: summary(), ...extra })

let scrollIntoView: ReturnType<typeof vi.fn>

beforeEach(() => {
  scrollIntoView = vi.fn()
  Element.prototype.scrollIntoView = scrollIntoView as unknown as typeof Element.prototype.scrollIntoView
})
afterEach(() => vi.unstubAllGlobals())

const toggle = (w: ReturnType<typeof mount>) => w.find('[data-test="plan-toggle"]')

describe('faixa do plano', () => {
  it('sessão rodando mostra título, posição e barra de progresso', () => {
    const w = mount(PlanStrip, { props: { session: session() } })
    expect(w.text()).toContain('Plano da loja')
    expect(w.text()).toContain('Tarefa 4 de 12: Faixa do plano')
    expect(w.text()).not.toContain('parado')
    const bar = w.find('[role="progressbar"]')
    expect(bar.attributes('aria-valuenow')).toBe('3')
    expect(bar.attributes('aria-valuemax')).toBe('12')
    expect(w.find('[data-test="plan-strip"]').classes()).not.toContain('opacity-60')
  })

  it('sessão parada mostra "· parado" e barra cinza, sem reduzir a opacidade do texto', () => {
    const w = mount(PlanStrip, { props: { session: session({ display_state: 'waiting' }) } })
    expect(w.find('[data-test="plan-strip"]').classes()).not.toContain('opacity-60')
    expect(w.find('[role="progressbar"] > div').classes()).toContain('bg-fg-muted')
    expect(w.text()).toContain('· parado')
  })

  it('CLI no meio de um turno não aparece como parado', () => {
    const w = mount(PlanStrip, { props: { session: session({ display_state: 'waiting', cli_running: true }) } })
    expect(w.text()).not.toContain('parado')
    expect(w.find('[role="progressbar"] > div').classes()).toContain('bg-primary')
  })

  it('CLI parado aparece como parado', () => {
    const w = mount(PlanStrip, { props: { session: session({ display_state: 'waiting', cli_running: false }) } })
    expect(w.text()).toContain('· parado')
  })

  it.each([
    ['plano 100%', session({ plan: summary({ done: 12, current: null }) })],
    ['sessão finalizada', session({ finished: true, display_state: 'finished' })],
    ['sem plano', session({ plan: null })],
  ])('não renderiza nada: %s', (_name, s) => {
    const w = mount(PlanStrip, { props: { session: s } })
    expect(w.find('[data-test="plan-strip"]').exists()).toBe(false)
    expect(w.text()).toBe('')
  })

  it('clicar abre a lista de tarefas com estados e rola a atual; clicar de novo recolhe', async () => {
    const fetchMock = routeFetch({ 'GET /api/sessions/s1/plan': () => jsonResponse(planState(summary())) })
    vi.stubGlobal('fetch', fetchMock)
    const w = mount(PlanStrip, { props: { session: session() }, attachTo: document.body })
    expect(toggle(w).attributes('aria-expanded')).toBe('false')
    await toggle(w).trigger('click')
    await flushPromises()
    expect(toggle(w).attributes('aria-expanded')).toBe('true')
    expect(fetchMock).toHaveBeenCalledWith('/api/sessions/s1/plan', expect.objectContaining({ method: 'GET' }))
    const items = w.findAll('[data-test="plan-task"]')
    expect(items).toHaveLength(5)
    expect(items[0]!.attributes('data-status')).toBe('done')
    expect(items[3]!.attributes('data-status')).toBe('current')
    expect(items[3]!.attributes('aria-current')).toBe('step')
    expect(items[4]!.attributes('data-status')).toBe('queued')
    expect(items[3]!.text()).toContain('Faixa do plano')
    expect(scrollIntoView).toHaveBeenCalledWith({ block: 'nearest' })
    await toggle(w).trigger('click')
    expect(toggle(w).attributes('aria-expanded')).toBe('false')
    expect(w.findAll('[data-test="plan-task"]')).toHaveLength(0)
    w.unmount()
  })

  it('no painel, o plano já vem aberto, compacto e sem largura máxima: concluídas recolhidas, a atual e a próxima', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/sessions/s1/plan': () => jsonResponse(planState(summary())) }))
    const w = mount(PlanStrip, { props: { session: session(), variant: 'panel' } })
    await flushPromises()
    expect(toggle(w).attributes('aria-expanded')).toBe('true')
    const items = w.findAll('[data-test="plan-task"]')
    expect(items.map((i) => i.attributes('data-status'))).toEqual(['current', 'queued'])
    expect(w.find('[data-test="plan-strip"]').classes()).not.toContain('max-w-(--chat-width)')
  })

  it('no painel, mostra título, "N de T", a barra, as concluídas recolhidas, a atual em destaque, 2 próximas e "+N depois"', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/sessions/s1/plan': () => jsonResponse(bigState()) }))
    const w = mount(PlanStrip, { props: { session: bigSession(), variant: 'panel' } })
    await flushPromises()
    const head = toggle(w).text()
    expect(head).toContain('Plano da loja')
    expect(head).toContain('15 de 19')
    expect(head).not.toContain('Tarefa 15 de 19')
    expect(w.find('[role="progressbar"]').attributes('aria-valuenow')).toBe('14')
    const done = w.find('[data-test="plan-done-toggle"]')
    expect(done.text()).toContain('14 concluídas')
    expect(done.attributes('aria-expanded')).toBe('false')
    expect(done.find('svg').classes()).toContain('text-primary')
    const items = w.findAll('[data-test="plan-task"]')
    expect(items.map((i) => i.attributes('data-status'))).toEqual(['current', 'queued', 'queued'])
    const current = items[0]!
    expect(current.text()).toContain('AGORA')
    expect(current.text()).toContain('Quinze')
    expect(current.classes()).toEqual(expect.arrayContaining(['rounded-[10px]', 'border', 'border-primary/30', 'bg-primary-tint', 'px-2.5', 'py-2']))
    expect(current.find('.cap').classes()).toContain('text-primary-soft')
    expect(current.attributes('aria-current')).toBe('step')
    expect(items[1]!.text()).toContain('Tarefa 16')
    expect(items[2]!.text()).toContain('Tarefa 17')
    expect(w.find('[data-test="plan-later"]').text()).toBe('+2 depois')
  })

  it('no painel, sem tarefas depois das 2 próximas não mostra "+N depois"; sem concluídas não mostra o recolhido', async () => {
    const plan = summary({ total: 2, done: 0, current: { number: 1, title: 'Única' } })
    const state: PlanState = { link: 'auto', path: plan.path, plan, tasks: [{ number: 1, title: 'Única', done: false }, { number: 2, title: 'Dois', done: false }] }
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/sessions/s1/plan': () => jsonResponse(state) }))
    const w = mount(PlanStrip, { props: { session: session({ plan }), variant: 'panel' } })
    await flushPromises()
    expect(w.find('[data-test="plan-later"]').exists()).toBe(false)
    expect(w.find('[data-test="plan-done-toggle"]').exists()).toBe(false)
    expect(w.findAll('[data-test="plan-task"]')).toHaveLength(2)
  })

  it.each([
    ['lista vazia', () => jsonResponse({ ...planState(summary()), tasks: [] })],
    ['lista ainda não carregada', () => new Promise<Response>(() => {})],
  ])('no painel, com %s o destaque AGORA usa a tarefa atual do resumo', async (_name, handler) => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/sessions/s1/plan': handler }))
    const w = mount(PlanStrip, { props: { session: session(), variant: 'panel' } })
    await flushPromises()
    const items = w.findAll('[data-test="plan-task"]')
    expect(items).toHaveLength(1)
    expect(items[0]!.attributes('data-status')).toBe('current')
    expect(items[0]!.attributes('aria-current')).toBe('step')
    expect(items[0]!.text()).toContain('AGORA')
    expect(items[0]!.text()).toContain('4.')
    expect(items[0]!.text()).toContain('Faixa do plano')
    expect(w.find('[data-test="plan-done-toggle"]').exists()).toBe(false)
    expect(w.find('[data-test="plan-later"]').exists()).toBe(false)
  })

  it('no painel, "N concluídas" abre e recolhe a lista das feitas, antes da atual', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/sessions/s1/plan': () => jsonResponse(bigState()) }))
    const w = mount(PlanStrip, { props: { session: bigSession(), variant: 'panel' } })
    await flushPromises()
    await w.find('[data-test="plan-done-toggle"]').trigger('click')
    expect(w.find('[data-test="plan-done-toggle"]').attributes('aria-expanded')).toBe('true')
    let statuses = w.findAll('[data-test="plan-task"]').map((i) => i.attributes('data-status'))
    expect(statuses).toHaveLength(17)
    expect(statuses.slice(0, 14).every((s) => s === 'done')).toBe(true)
    expect(statuses.slice(14)).toEqual(['current', 'queued', 'queued'])
    await w.find('[data-test="plan-done-toggle"]').trigger('click')
    statuses = w.findAll('[data-test="plan-task"]').map((i) => i.attributes('data-status'))
    expect(statuses).toEqual(['current', 'queued', 'queued'])
  })

  it('no painel, a lista das feitas abre dentro de um Collapse e o chevron acompanha o tempo do app', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/sessions/s1/plan': () => jsonResponse(bigState()) }))
    const w = mount(PlanStrip, { props: { session: bigSession(), variant: 'panel' } })
    await flushPromises()
    const collapse = w.findComponent(Collapse)
    expect(collapse.props('open')).toBe(false)
    expect(w.find('[data-test="plan-done-toggle"] svg:last-child').classes()).toEqual(expect.arrayContaining(['duration-(--motion-enter)', 'ease-(--ease-maestro)']))
    await w.find('[data-test="plan-done-toggle"]').trigger('click')
    expect(collapse.props('open')).toBe(true)
    expect(w.find('[data-test="plan-done-toggle"]').attributes('aria-expanded')).toBe('true')
  })

  it('no painel, "Abrir plano" fica no rodapé junto do espaço das ações e chama o editor', async () => {
    const fetchMock = routeFetch({
      'GET /api/sessions/s1/plan': () => jsonResponse(planState(summary())),
      'POST /api/open-in-editor': () => jsonResponse(undefined, 204),
    })
    vi.stubGlobal('fetch', fetchMock)
    const w = mount(PlanStrip, {
      props: { session: session(), variant: 'panel' },
      slots: { actions: '<button data-test="slot-action">Trocar plano…</button>' },
    })
    await flushPromises()
    const footer = w.find('[data-test="plan-footer"]')
    expect(footer.find('[data-test="plan-open"]').exists()).toBe(true)
    expect(footer.find('[data-test="slot-action"]').exists()).toBe(true)
    expect(toggle(w).element.parentElement!.querySelector('[data-test="plan-open"]')).toBeNull()
    await footer.find('[data-test="plan-open"]').trigger('click')
    await flushPromises()
    expect(fetchMock.mock.calls.some(([url]) => url === '/api/open-in-editor')).toBe(true)
  })

  it('na faixa, "Abrir plano" continua no topo e não há rodapé', () => {
    const w = mount(PlanStrip, { props: { session: session() }, slots: { actions: '<button data-test="slot-action">x</button>' } })
    expect(w.find('[data-test="plan-footer"]').exists()).toBe(false)
    expect(toggle(w).element.parentElement!.querySelector('[data-test="plan-open"]')).not.toBeNull()
    expect(w.find('[data-test="slot-action"]').exists()).toBe(false)
  })

  it('no painel, o botão recolhe o plano', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/sessions/s1/plan': () => jsonResponse(planState(summary())) }))
    const w = mount(PlanStrip, { props: { session: session(), variant: 'panel' } })
    await flushPromises()
    await toggle(w).trigger('click')
    expect(toggle(w).attributes('aria-expanded')).toBe('false')
    expect(w.findAll('[data-test="plan-task"]')).toHaveLength(0)
    expect(w.find('[data-test="plan-done-toggle"]').exists()).toBe(false)
  })

  // The "(na fila)" labels are sr-only (position: absolute). Without a positioned list they
  // escape the scroll container and stretch the page below the window.
  it.each([['na faixa', undefined], ['no painel', 'panel']] as const)('%s, a lista contém os textos só para leitor de tela', async (_label, variant) => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/sessions/s1/plan': () => jsonResponse(planState(summary())) }))
    const w = mount(PlanStrip, { props: { session: session(), variant } })
    await flushPromises()
    if (variant === undefined) {
      await toggle(w).trigger('click')
      await flushPromises()
    }
    expect(w.find('[data-test="plan-task"]').find('.sr-only').exists()).toBe(true)
    expect(w.find('[data-test="plan-task"]').element.parentElement!.classList).toContain('relative')
  })

  it('na faixa, a lista continua fechada e com largura máxima', () => {
    const w = mount(PlanStrip, { props: { session: session() } })
    expect(toggle(w).attributes('aria-expanded')).toBe('false')
    expect(w.find('[data-test="plan-strip"]').classes()).toContain('max-w-(--chat-width)')
  })

  it('no painel, trocar de conversa reabre a lista da nova', async () => {
    const fetchMock = routeFetch({
      'GET /api/sessions/s1/plan': () => jsonResponse(planState(summary())),
      'GET /api/sessions/s2/plan': () => jsonResponse(planState(summary())),
    })
    vi.stubGlobal('fetch', fetchMock)
    const w = mount(PlanStrip, { props: { session: session(), variant: 'panel' } })
    await flushPromises()
    await w.setProps({ session: session({ session_id: 's2' }) })
    await flushPromises()
    expect(fetchMock).toHaveBeenCalledWith('/api/sessions/s2/plan', expect.objectContaining({ method: 'GET' }))
    expect(toggle(w).attributes('aria-expanded')).toBe('true')
    expect(w.findAll('[data-test="plan-task"]')).toHaveLength(2)
  })

  it('busca a lista de novo quando done muda com a lista aberta', async () => {
    const fetchMock = routeFetch({ 'GET /api/sessions/s1/plan': () => jsonResponse(planState(summary())) })
    vi.stubGlobal('fetch', fetchMock)
    const w = mount(PlanStrip, { props: { session: session() } })
    await toggle(w).trigger('click')
    await flushPromises()
    expect(fetchMock).toHaveBeenCalledTimes(1)
    await w.setProps({ session: session({ plan: summary({ done: 4, current: { number: 5, title: 'Quinta' } }) }) })
    await flushPromises()
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('busca a lista de novo quando o caminho do plano muda com a lista aberta', async () => {
    const fetchMock = routeFetch({ 'GET /api/sessions/s1/plan': () => jsonResponse(planState(summary())) })
    vi.stubGlobal('fetch', fetchMock)
    const w = mount(PlanStrip, { props: { session: session() } })
    await toggle(w).trigger('click')
    await flushPromises()
    expect(fetchMock).toHaveBeenCalledTimes(1)
    await w.setProps({ session: session({ plan: summary({ path: '/home/vi/dev/loja-online/docs/outro.md' }) }) })
    await flushPromises()
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('lista com números de tarefa repetidos mostra todas com o estado certo', async () => {
    const dup = summary({ current: { number: 1, title: 'Repetida A' }, done: 0, total: 3 })
    const state: PlanState = {
      link: 'auto',
      path: dup.path,
      plan: dup,
      tasks: [
        { number: 1, title: 'Repetida A', done: false },
        { number: 1, title: 'Repetida B', done: false },
        { number: 2, title: 'Depois', done: false },
      ],
    }
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/sessions/s1/plan': () => jsonResponse(state) }))
    const w = mount(PlanStrip, { props: { session: session({ plan: dup }) } })
    await toggle(w).trigger('click')
    await flushPromises()
    const items = w.findAll('[data-test="plan-task"]')
    expect(items.map((i) => i.text())).toEqual([
      expect.stringContaining('Repetida A'),
      expect.stringContaining('Repetida B'),
      expect.stringContaining('Depois'),
    ])
    expect(items.map((i) => i.attributes('data-status'))).toEqual(['current', 'queued', 'queued'])
  })

  it('não busca de novo quando done muda com a lista fechada', async () => {
    const fetchMock = routeFetch({ 'GET /api/sessions/s1/plan': () => jsonResponse(planState(summary())) })
    vi.stubGlobal('fetch', fetchMock)
    const w = mount(PlanStrip, { props: { session: session() } })
    await w.setProps({ session: session({ plan: summary({ done: 4 }) }) })
    await flushPromises()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('falha ao buscar a lista vira mensagem legível', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/sessions/s1/plan': () => jsonResponse({ detail: 'Plano indisponível.' }, 404) }))
    const w = mount(PlanStrip, { props: { session: session() } })
    await toggle(w).trigger('click')
    await flushPromises()
    expect(w.find('[role="alert"]').text()).toBe('Plano indisponível.')
  })

  it('"Abrir plano" chama o editor com o caminho do plano', async () => {
    const fetchMock = routeFetch({ 'POST /api/open-in-editor': () => jsonResponse(undefined, 204) })
    vi.stubGlobal('fetch', fetchMock)
    const w = mount(PlanStrip, { props: { session: session() } })
    await w.find('[data-test="plan-open"]').trigger('click')
    await flushPromises()
    const call = fetchMock.mock.calls.find(([url]) => url === '/api/open-in-editor')!
    expect(JSON.parse(call[1]!.body as string)).toEqual({ path: '/home/vi/dev/loja-online/docs/plan.md' })
    expect(w.find('[role="alert"]').exists()).toBe(false)
  })

  it('erro ao abrir o plano vira mensagem legível', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'POST /api/open-in-editor': () => jsonResponse({ detail: 'Editor não encontrado.' }, 500) }))
    const w = mount(PlanStrip, { props: { session: session() } })
    await w.find('[data-test="plan-open"]').trigger('click')
    await flushPromises()
    expect(w.find('[role="alert"]').text()).toBe('Editor não encontrado.')
  })
})
