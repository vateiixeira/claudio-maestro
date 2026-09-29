import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { jsonResponse, makeSession, routeFetch } from '../../../test/factories'
import PlanStrip from '../PlanStrip.vue'
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
