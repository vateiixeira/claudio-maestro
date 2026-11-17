import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import NowRow from '../NowRow.vue'
import { createAppRouter } from '../../../router'
import { useProjectsStore } from '../../../stores/projects'
import { jsonResponse, makeProject, makeSession, routeFetch } from '../../../test/factories'
import type { PlanSummary, Session } from '../../../types/api'

enableAutoUnmount(afterEach)
let pinia: Pinia
const now = Math.floor(Date.now() / 1000)
const plan: PlanSummary = { path: 'docs/plan.md', title: 'Plano', total: 12, done: 3, current: { number: 4, title: 'Criar o selo' } }
const tool = { prompt_id: 'p1', tool_name: 'Bash', summary: 'ls', can_allow_always: false }

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  const projects = useProjectsStore(pinia)
  projects.projects = [makeProject({ id: 1, name: 'loja-online', color: '#B28CFF' })]
  projects.loaded = true
})
afterEach(() => vi.unstubAllGlobals())

function mountRow(overrides: Partial<Session> = {}) {
  const router = createAppRouter(createMemoryHistory())
  const session = makeSession({ session_id: 's1', title: 'Construir o painel', display_state: 'running', state: 'running', last_activity_at: now, ...overrides })
  return mount(NowRow, { props: { session }, global: { plugins: [pinia, router] } })
}

describe('linha de Agora', () => {
  it('mostra o título como link para a conversa, o projeto e o tempo', () => {
    const wrapper = mountRow()
    const link = wrapper.get('[data-test="now-row-link"]')
    expect(link.text()).toBe('Construir o painel')
    expect(link.attributes('href')).toBe('/sessions/s1')
    expect(wrapper.get('[data-test="project-tag"]').text()).toBe('loja-online')
    expect(wrapper.get('[data-test="now-row-time"]').text()).toBe('agora')
  })

  it('em execução, o ícone é o arco girando e a atividade é a última ação', () => {
    const wrapper = mountRow({ last_action: 'Edit main.py' })
    expect(wrapper.get('[data-shape]').attributes('data-shape')).toBe('spinner')
    expect(wrapper.get('[data-test="session-activity"]').text()).toBe('Edit main.py')
  })

  it('mostra as etapas do plano quando há tarefa atual', () => {
    const wrapper = mountRow({ plan })
    expect(wrapper.find('[data-test="plan-segments"]').exists()).toBe(true)
    expect(wrapper.get('[data-test="session-activity"]').text()).toContain('Criar o selo')
  })

  it('espera que precisa de você mostra o motivo em laranja', () => {
    const wrapper = mountRow({ display_state: 'waiting', state: 'awaiting_decision', awaiting_decision: true, pending_kind: 'question' })
    expect(wrapper.get('[data-shape]').attributes('data-shape')).toBe('triangle')
    expect(wrapper.get('[data-test="session-activity"]').classes()).toContain('text-secondary-soft')
  })

  it('o projeto e a atividade descem para baixo do título nas telas estreitas', () => {
    const wrapper = mountRow({ last_action: 'Edit main.py' })
    const row = wrapper.get('[data-test="now-row-grid"]')
    expect(row.classes()).toContain('md:grid-cols-[0.875rem_minmax(0,18.75rem)_8.75rem_minmax(0,1fr)_3.875rem]')
    expect(wrapper.get('[data-test="now-row-project"]').classes()).toContain('max-md:row-start-2')
    expect(wrapper.get('[data-test="now-row-activity"]').classes()).toContain('max-md:row-start-3')
  })

  it('mantém a célula da atividade mesmo vazia, para as colunas alinharem', () => {
    const wrapper = mountRow({ last_action: null })
    expect(wrapper.find('[data-test="now-row-activity"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="session-activity"]').exists()).toBe(false)
  })
})

describe('linha de Agora com permissão pendente', () => {
  const asking = { display_state: 'waiting' as const, state: 'awaiting_decision' as const, awaiting_decision: true, pending_kind: 'tool' as const, pending_permission: tool }

  it('sem pedido não mostra Permitir nem Negar', () => {
    const wrapper = mountRow()
    expect(wrapper.find('[data-test="now-allow"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="now-deny"]').exists()).toBe(false)
  })

  it('permite e nega pela linha, com o nome da ferramenta no rótulo', async () => {
    const fetch = routeFetch({ 'POST /api/sessions/s1/prompts/p1': () => jsonResponse(undefined, 204) })
    vi.stubGlobal('fetch', fetch)
    const wrapper = mountRow(asking)
    expect(wrapper.get('[data-test="now-allow"]').attributes('aria-label')).toBe('Permitir Bash em Construir o painel')
    expect(wrapper.get('[data-test="now-deny"]').attributes('aria-label')).toBe('Negar Bash em Construir o painel')

    await wrapper.get('[data-test="now-allow"]').trigger('click')
    await flushPromises()
    const call = fetch.mock.calls.find(([url]) => url === '/api/sessions/s1/prompts/p1')!
    expect(JSON.parse(call[1]!.body as string)).toEqual({ decision: 'allow_once' })
    expect(wrapper.get('[role="status"]').text()).toBe('Resposta enviada. Atualizando…')
    expect(wrapper.find('[data-test="now-allow"]').exists()).toBe(false)
  })

  it('nega pelo botão Negar', async () => {
    const fetch = routeFetch({ 'POST /api/sessions/s1/prompts/p1': () => jsonResponse(undefined, 204) })
    vi.stubGlobal('fetch', fetch)
    const wrapper = mountRow(asking)
    await wrapper.get('[data-test="now-deny"]').trigger('click')
    await flushPromises()
    const call = fetch.mock.calls.find(([url]) => url === '/api/sessions/s1/prompts/p1')!
    expect(JSON.parse(call[1]!.body as string)).toEqual({ decision: 'deny' })
  })

  it('mostra o erro quando a resposta falha', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'POST /api/sessions/s1/prompts/p1': () => jsonResponse({ detail: 'Falhou.' }, 500) }))
    const wrapper = mountRow(asking)
    await wrapper.get('[data-test="now-allow"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('Falhou.')
  })
})
