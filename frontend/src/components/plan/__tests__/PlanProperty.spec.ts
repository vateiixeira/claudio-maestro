import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import PlanProperty from '../PlanProperty.vue'
import { useSessionsStore } from '../../../stores/sessions'
import { jsonResponse, makeSession, routeFetch } from '../../../test/factories'
import type { PlanState, PlanSummary } from '../../../types/api'

enableAutoUnmount(afterEach)
let pinia: Pinia

const summary = (overrides: Partial<PlanSummary> = {}): PlanSummary => ({
  path: '/home/vi/dev/loja-online/docs/superpowers/plans/2026-09-29-carrinho.md',
  title: 'Carrinho de compras',
  total: 12,
  done: 3,
  current: { number: 4, title: 'Somar frete' },
  ...overrides,
})
const state = (overrides: Partial<PlanState> = {}): PlanState => ({
  link: 'auto',
  path: summary().path,
  plan: summary(),
  tasks: [],
  ...overrides,
})
const none: PlanState = { link: 'auto', path: null, plan: null, tasks: [] }
const off: PlanState = { link: 'off', path: null, plan: null, tasks: [] }

const plans = [
  { path: '/home/vi/dev/loja-online/docs/superpowers/plans/a.md', title: 'Carrinho de compras', total: 12, done: 3 },
  { path: '/home/vi/dev/loja-online/docs/superpowers/plans/b.md', title: 'Pagamentos', total: 5, done: 0 },
]

type Handlers = Record<string, (init: RequestInit | undefined) => Response | Promise<Response>>

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  useSessionsStore(pinia).setForProject(1, [makeSession({ session_id: 's1' })])
})
afterEach(() => vi.unstubAllGlobals())

async function mountProperty(handlers: Handlers, options: { attachTo?: HTMLElement } = {}) {
  const fetchMock = routeFetch(handlers)
  vi.stubGlobal('fetch', fetchMock)
  const wrapper = mount(PlanProperty, {
    props: { sessionId: 's1', projectId: 1 },
    global: { plugins: [pinia] },
    ...options,
  })
  await flushPromises()
  return { wrapper, fetchMock }
}

const calls = (fetchMock: ReturnType<typeof routeFetch>, key: string) =>
  fetchMock.mock.calls.filter(([url, init]) => `${init?.method ?? 'GET'} ${url}` === key)

const buttonByText = (wrapper: ReturnType<typeof mount>, text: string) =>
  wrapper.findAll('button').find((b) => b.text().includes(text))

describe('propriedade Plano', () => {
  it('sem vínculo mostra Nenhum e o botão de escolher', async () => {
    const { wrapper } = await mountProperty({ 'GET /api/sessions/s1/plan': () => jsonResponse(none) })

    expect(wrapper.text()).toContain('Plano')
    expect(wrapper.find('[data-test="prop-plan"]').text()).toContain('Nenhum')
    expect(buttonByText(wrapper, 'Escolher plano…')).toBeTruthy()
    expect(buttonByText(wrapper, 'Desligar')).toBeUndefined()
  })

  it('com plano mostra o nome e a posição', async () => {
    const { wrapper } = await mountProperty({ 'GET /api/sessions/s1/plan': () => jsonResponse(state()) })

    const value = wrapper.find('[data-test="prop-plan"]').text()
    expect(value).toContain('Carrinho de compras')
    expect(value).toContain('4 de 12')
    expect(buttonByText(wrapper, 'Trocar plano…')).toBeTruthy()
    expect(buttonByText(wrapper, 'Desligar')).toBeTruthy()
  })

  it('com o plano em 100% mostra Concluído', async () => {
    const { wrapper } = await mountProperty({
      'GET /api/sessions/s1/plan': () => jsonResponse(state({ plan: summary({ done: 12, current: null }) })),
    })

    const value = wrapper.find('[data-test="prop-plan"]').text()
    expect(value).toContain('Carrinho de compras')
    expect(value).toContain('Concluído')
    expect(value).not.toContain('de 12')
  })

  it('com caminho e sem resumo mostra Plano indisponível e o caminho', async () => {
    const { wrapper } = await mountProperty({
      'GET /api/sessions/s1/plan': () => jsonResponse(state({ plan: null, link: 'manual' })),
    })

    const value = wrapper.find('[data-test="prop-plan"]').text()
    expect(value).toContain('Plano indisponível')
    expect(value).toContain('docs/superpowers/plans/2026-09-29-carrinho.md')
    expect(buttonByText(wrapper, 'Trocar plano…')).toBeTruthy()
    expect(buttonByText(wrapper, 'Desligar')).toBeTruthy()
  })

  it('abre a lista de planos do projeto e vincula o escolhido', async () => {
    const chosen = state({
      link: 'manual',
      path: plans[1]!.path,
      plan: summary({ path: plans[1]!.path, title: 'Pagamentos', total: 5, done: 0, current: { number: 1, title: 'Gateway' } }),
    })
    const { wrapper, fetchMock } = await mountProperty({
      'GET /api/sessions/s1/plan': () => jsonResponse(state()),
      'GET /api/projects/1/plans': () => jsonResponse(plans),
      'PUT /api/sessions/s1/plan': () => jsonResponse(chosen),
    })

    await buttonByText(wrapper, 'Trocar plano…')!.trigger('click')
    await flushPromises()

    const items = wrapper.findAll('[role="menuitem"]')
    expect(items).toHaveLength(2)
    expect(items[0]!.text()).toContain('Carrinho de compras')
    expect(items[0]!.text()).toContain('3/12')
    expect(items[1]!.text()).toContain('Pagamentos')
    expect(items[1]!.text()).toContain('0/5')

    await items[1]!.trigger('click')
    await flushPromises()

    const put = calls(fetchMock, 'PUT /api/sessions/s1/plan')
    expect(put).toHaveLength(1)
    expect(JSON.parse(put[0]![1]!.body as string)).toEqual({ path: plans[1]!.path })
    expect(wrapper.find('[role="menu"]').exists()).toBe(false)
    const value = wrapper.find('[data-test="prop-plan"]').text()
    expect(value).toContain('Pagamentos')
    expect(value).toContain('1 de 5')
  })

  it('lista vazia avisa que não há planos na pasta', async () => {
    const { wrapper } = await mountProperty({
      'GET /api/sessions/s1/plan': () => jsonResponse(none),
      'GET /api/projects/1/plans': () => jsonResponse([]),
    })

    await buttonByText(wrapper, 'Escolher plano…')!.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('Nenhum plano em docs/superpowers/plans/')
    expect(wrapper.findAll('[role="menuitem"]')).toHaveLength(0)
  })

  it('Desligar chama DELETE e volta a Nenhum', async () => {
    const { wrapper, fetchMock } = await mountProperty({
      'GET /api/sessions/s1/plan': () => jsonResponse(state()),
      'DELETE /api/sessions/s1/plan': () => jsonResponse(off),
    })

    await buttonByText(wrapper, 'Desligar')!.trigger('click')
    await flushPromises()

    expect(calls(fetchMock, 'DELETE /api/sessions/s1/plan')).toHaveLength(1)
    expect(wrapper.find('[data-test="prop-plan"]').text()).toContain('Nenhum')
    expect(buttonByText(wrapper, 'Desligar')).toBeUndefined()
    expect(buttonByText(wrapper, 'Ligar automaticamente')).toBeTruthy()
  })

  it('com vínculo desligado Ligar automaticamente chama PUT com auto', async () => {
    const { wrapper, fetchMock } = await mountProperty({
      'GET /api/sessions/s1/plan': () => jsonResponse(off),
      'PUT /api/sessions/s1/plan': () => jsonResponse(state()),
    })

    await buttonByText(wrapper, 'Ligar automaticamente')!.trigger('click')
    await flushPromises()

    const put = calls(fetchMock, 'PUT /api/sessions/s1/plan')
    expect(put).toHaveLength(1)
    expect(JSON.parse(put[0]![1]!.body as string)).toEqual({ auto: true })
    expect(wrapper.find('[data-test="prop-plan"]').text()).toContain('4 de 12')
    expect(buttonByText(wrapper, 'Ligar automaticamente')).toBeUndefined()
  })

  it('mostra o erro da rota e reabilita os botões', async () => {
    const { wrapper } = await mountProperty({
      'GET /api/sessions/s1/plan': () => jsonResponse(state()),
      'DELETE /api/sessions/s1/plan': () => jsonResponse({ detail: 'Não foi possível desligar o plano.' }, 500),
    })

    await buttonByText(wrapper, 'Desligar')!.trigger('click')
    await flushPromises()

    expect(wrapper.find('[role="alert"]').text()).toContain('Não foi possível desligar o plano.')
    expect(buttonByText(wrapper, 'Desligar')!.attributes('disabled')).toBeUndefined()
    expect(buttonByText(wrapper, 'Trocar plano…')!.attributes('disabled')).toBeUndefined()
  })

  it('erro ao vincular aparece e os botões continuam utilizáveis', async () => {
    const { wrapper } = await mountProperty({
      'GET /api/sessions/s1/plan': () => jsonResponse(none),
      'GET /api/projects/1/plans': () => jsonResponse(plans),
      'PUT /api/sessions/s1/plan': () => jsonResponse({ detail: 'Plano fora de um projeto registrado.' }, 400),
    })

    await buttonByText(wrapper, 'Escolher plano…')!.trigger('click')
    await flushPromises()
    await wrapper.findAll('[role="menuitem"]')[0]!.trigger('click')
    await flushPromises()

    expect(wrapper.find('[role="alert"]').text()).toContain('Plano fora de um projeto registrado.')
    expect(buttonByText(wrapper, 'Escolher plano…')!.attributes('disabled')).toBeUndefined()
  })

  it('erro ao listar os planos aparece como alerta', async () => {
    const { wrapper } = await mountProperty({
      'GET /api/sessions/s1/plan': () => jsonResponse(none),
      'GET /api/projects/1/plans': () => jsonResponse({ detail: 'Projeto indisponível.' }, 404),
    })

    await buttonByText(wrapper, 'Escolher plano…')!.trigger('click')
    await flushPromises()

    expect(wrapper.find('[role="alert"]').text()).toContain('Projeto indisponível.')
    expect(wrapper.find('[role="menu"]').exists()).toBe(false)
  })

  it('a lista abre com foco no primeiro item, navega por setas e fecha com Esc consumindo o evento', async () => {
    const host = document.createElement('div')
    document.body.appendChild(host)
    const { wrapper } = await mountProperty({
      'GET /api/sessions/s1/plan': () => jsonResponse(state()),
      'GET /api/projects/1/plans': () => jsonResponse(plans),
    }, { attachTo: host })

    const trigger = buttonByText(wrapper, 'Trocar plano…')!
    expect(trigger.attributes('aria-expanded')).toBe('false')
    await trigger.trigger('click')
    await flushPromises()
    expect(trigger.attributes('aria-expanded')).toBe('true')

    const items = wrapper.findAll('[role="menuitem"]')
    expect(document.activeElement).toBe(items[0]!.element)
    await items[0]!.trigger('keydown', { key: 'ArrowDown' })
    expect(document.activeElement).toBe(items[1]!.element)

    const escape = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
    items[1]!.element.dispatchEvent(escape)
    await flushPromises()

    expect(escape.defaultPrevented).toBe(true)
    expect(wrapper.find('[role="menu"]').exists()).toBe(false)
    expect(trigger.attributes('aria-expanded')).toBe('false')
    expect(document.activeElement).toBe(trigger.element)
    wrapper.unmount()
    host.remove()
  })

  it('com a lista vazia não usa role menu e o Esc no gatilho fecha o aviso sem chegar à gaveta', async () => {
    const host = document.createElement('div')
    document.body.appendChild(host)
    const { wrapper } = await mountProperty({
      'GET /api/sessions/s1/plan': () => jsonResponse(none),
      'GET /api/projects/1/plans': () => jsonResponse([]),
    }, { attachTo: host })
    const outer = vi.fn()
    window.addEventListener('keydown', outer)

    const trigger = buttonByText(wrapper, 'Escolher plano…')!
    await trigger.trigger('click')
    await flushPromises()
    expect(wrapper.find('[role="menu"]').exists()).toBe(false)
    expect(wrapper.find('[role="status"]').text()).toContain('Nenhum plano em docs/superpowers/plans/')
    expect(trigger.attributes('aria-expanded')).toBe('true')

    const escape = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
    trigger.element.dispatchEvent(escape)
    await flushPromises()

    expect(escape.defaultPrevented).toBe(true)
    expect(wrapper.find('[role="status"]').exists()).toBe(false)
    expect(trigger.attributes('aria-expanded')).toBe('false')
    expect(document.activeElement).toBe(trigger.element)
    expect(outer.mock.calls.every(([event]) => (event as KeyboardEvent).defaultPrevented)).toBe(true)
    window.removeEventListener('keydown', outer)
    wrapper.unmount()
    host.remove()
  })

  it('se a busca inicial falhar mostra o erro e Tentar de novo recarrega', async () => {
    let fail = true
    const { wrapper, fetchMock } = await mountProperty({
      'GET /api/sessions/s1/plan': () => (fail ? jsonResponse({ detail: 'Servidor indisponível.' }, 500) : jsonResponse(state())),
    })

    expect(wrapper.find('[role="alert"]').text()).toContain('Servidor indisponível.')
    expect(buttonByText(wrapper, 'Trocar plano…')).toBeUndefined()

    fail = false
    await buttonByText(wrapper, 'Tentar de novo')!.trigger('click')
    await flushPromises()

    expect(calls(fetchMock, 'GET /api/sessions/s1/plan')).toHaveLength(2)
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(buttonByText(wrapper, 'Tentar de novo')).toBeUndefined()
    expect(wrapper.find('[data-test="prop-plan"]').text()).toContain('4 de 12')
  })

  it('busca o estado de novo quando o plano da conversa muda no store', async () => {
    let current = state()
    const { fetchMock, wrapper } = await mountProperty({ 'GET /api/sessions/s1/plan': () => jsonResponse(current) })
    expect(calls(fetchMock, 'GET /api/sessions/s1/plan')).toHaveLength(1)

    current = state({ plan: summary({ done: 4, current: { number: 5, title: 'Aplicar cupom' } }) })
    useSessionsStore(pinia).setForProject(1, [makeSession({ session_id: 's1', plan: current.plan })])
    await flushPromises()

    expect(calls(fetchMock, 'GET /api/sessions/s1/plan')).toHaveLength(2)
    expect(wrapper.find('[data-test="prop-plan"]').text()).toContain('5 de 12')
  })

  it('não busca de novo quando o plano continua igual', async () => {
    const plan = summary()
    useSessionsStore(pinia).setForProject(1, [makeSession({ session_id: 's1', plan })])
    const { fetchMock } = await mountProperty({ 'GET /api/sessions/s1/plan': () => jsonResponse(state()) })

    useSessionsStore(pinia).setForProject(1, [makeSession({ session_id: 's1', plan: { ...plan }, title: 'Outro título' })])
    await flushPromises()

    expect(calls(fetchMock, 'GET /api/sessions/s1/plan')).toHaveLength(1)
  })
})
