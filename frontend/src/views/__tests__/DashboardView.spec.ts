import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import DashboardView from '../DashboardView.vue'
import { createAppRouter } from '../../router'
import { useGitStore } from '../../stores/git'
import { useProjectsStore } from '../../stores/projects'
import { useSessionsStore } from '../../stores/sessions'
import { jsonResponse, makeGitRepo, makeProject, makeSession, routeFetch } from '../../test/factories'

vi.mock('../../stores/realtime', () => ({ loadEverything: vi.fn(() => Promise.resolve()) }))
import { loadEverything } from '../../stores/realtime'

enableAutoUnmount(afterEach)
let pinia: Pinia
const now = Math.floor(Date.now() / 1000)

beforeEach(() => {
  vi.mocked(loadEverything).mockClear()
  pinia = createPinia()
  setActivePinia(pinia)
  const projects = useProjectsStore(pinia)
  projects.projects = [makeProject({ id: 1, name: 'a' }), makeProject({ id: 2, name: 'b', path: '/b' })]
  projects.loaded = true
  useSessionsStore(pinia).loaded = true
  useGitStore(pinia).set(1, [makeGitRepo({ changed: { staged: 0, unstaged: 2, untracked: 1 } })])
  useGitStore(pinia).set(2, [makeGitRepo({ path: '/b' })])
  useSessionsStore(pinia).setForProject(1, [
    makeSession({ session_id: 'r', title: 'Rodando', display_state: 'running', state: 'running', last_action: 'Edit main.py', last_activity_at: now }),
    makeSession({
      session_id: 'w', title: 'Pede', display_state: 'waiting', state: 'awaiting_decision', awaiting_decision: true,
      pending_kind: 'tool', pending_permission: { prompt_id: 'p1', tool_name: 'Bash', summary: 'ls', can_allow_always: false },
      last_activity_at: now,
    }),
    makeSession({ session_id: 'f', title: 'Feita', display_state: 'finished', finished: true, finished_at: now, last_activity_at: now }),
    makeSession({ session_id: 'old', title: 'Ontem', display_state: 'finished', finished: true, finished_at: now - 2 * 86400, last_activity_at: now - 2 * 86400 }),
  ])
})
afterEach(() => vi.unstubAllGlobals())

async function mountDashboard(activity: () => Response = () => jsonResponse([])) {
  const fetch = routeFetch({
    'GET /api/activity?days=14': activity,
    'POST /api/sessions/w/prompts/p1': () => jsonResponse(undefined, 204),
  })
  vi.stubGlobal('fetch', fetch)
  const router = createAppRouter(createMemoryHistory())
  const wrapper = mount(DashboardView, { global: { plugins: [pinia, router] } })
  await flushPromises()
  return { wrapper, fetch }
}

describe('Dashboard', () => {
  it('mostra cartões das conversas ativas com a última ação', async () => {
    const { wrapper } = await mountDashboard()
    const cards = wrapper.findAll('[data-test="now-card"]')
    expect(cards.map((c) => c.find('a').text())).toEqual(['Pede', 'Rodando'])
    expect(cards[0]!.text()).toContain('Pede permissão: Bash')
    expect(cards[1]!.text()).toContain('Edit main.py')
  })

  it('permite pelo cartão', async () => {
    const { wrapper, fetch } = await mountDashboard()
    await wrapper.find('[data-test="now-allow"]').trigger('click')
    await flushPromises()
    const call = fetch.mock.calls.find(([url]) => url === '/api/sessions/w/prompts/p1')!
    expect(JSON.parse(call[1]!.body as string)).toEqual({ decision: 'allow_once' })
  })

  it('mostra os números com links', async () => {
    const { wrapper } = await mountDashboard()
    expect(wrapper.find('[data-test="stat-running"]').text()).toContain('1')
    expect(wrapper.find('[data-test="stat-running"]').attributes('href')).toBe('/inbox?aba=em-execucao')
    expect(wrapper.find('[data-test="stat-waiting"]').text()).toContain('1')
    expect(wrapper.find('[data-test="stat-finished-today"]').text()).toContain('1')
    expect(wrapper.find('[data-test="stat-finished-today"]').attributes('href')).toBe('/entregas')
    expect(wrapper.find('[data-test="stat-projects-changes"]').text()).toContain('1')
  })

  it('falha do gráfico não derruba o resto e pode tentar de novo', async () => {
    let calls = 0
    const { wrapper } = await mountDashboard(() => (++calls === 1 ? jsonResponse({ detail: 'x' }, 500) : jsonResponse([])))

    expect(wrapper.find('[data-test="activity-error"]').text()).toContain('Não foi possível carregar a atividade')
    expect(wrapper.find('[data-test="activity-error"]').classes()).toContain('text-diff-del-fg')
    expect(wrapper.findAll('[data-test="now-card"]')).toHaveLength(2)
    await wrapper.find('[data-test="activity-retry"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-test="activity-empty"]').exists()).toBe(true)
  })

  it('Conversas recentes e Projetos dividem a linha em duas colunas nas telas largas', async () => {
    const { wrapper } = await mountDashboard()
    const recent = wrapper.find('[data-test="recent-list"]').element.parentElement!
    const projects = wrapper.find('[data-test="projects-list"]').element.parentElement!
    expect(recent).toBe(projects)
    expect(recent.className).toContain('lg:grid-cols-2')
  })

  it('conta e destaca por projeto só quem precisa de você', async () => {
    useSessionsStore(pinia).setForProject(1, [
      makeSession({ session_id: 'calm', display_state: 'waiting', state: 'closed', unread: false }),
    ])
    useSessionsStore(pinia).setForProject(2, [
      makeSession({ session_id: 'ask', project_id: 2, display_state: 'waiting', state: 'closed', pending_kind: 'question' }),
    ])
    const { wrapper } = await mountDashboard()
    const rows = wrapper.findAll('[data-test="projects-list"] a')
    expect(rows[0]!.find('[data-test="project-waiting"]').exists()).toBe(false)
    expect(rows[1]!.find('[data-test="project-waiting"]').text()).toBe('1')
  })

  it('lista conversas recentes e projetos', async () => {
    const { wrapper } = await mountDashboard()
    expect(wrapper.findAll('[data-test="recent-list"] [data-test="conversation-row"]').length).toBeLessThanOrEqual(8)
    expect(wrapper.find('[data-test="projects-list"]').text()).toContain('3 arquivos')
  })

  it('sem conversas ativas mostra o aviso', async () => {
    useSessionsStore(pinia).setForProject(1, [])
    const { wrapper } = await mountDashboard()
    expect(wrapper.find('[data-test="now-empty"]').text()).toBe('Nenhuma conversa ativa agora.')
  })

  it('uma conversa reaberta com finished_at antigo não conta como finalizada hoje', async () => {
    useSessionsStore(pinia).setForProject(1, [
      makeSession({ session_id: 'f', title: 'Feita', display_state: 'finished', finished: true, finished_at: now, last_activity_at: now }),
      makeSession({ session_id: 're', title: 'Reaberta', display_state: 'running', finished: false, finished_at: now, last_activity_at: now }),
    ])
    const { wrapper } = await mountDashboard()
    expect(wrapper.find('[data-test="stat-finished-today"] span').text()).toBe('1')
  })

  it('enquanto as conversas carregam mostra "Carregando…" e nenhum zero nem aviso de vazio', async () => {
    useSessionsStore(pinia).loaded = false
    useSessionsStore(pinia).setForProject(1, [])
    const { wrapper } = await mountDashboard()
    expect(wrapper.find('[data-test="load-loading"]').text()).toBe('Carregando…')
    expect(wrapper.find('[data-test="now-empty"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="stat-running"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="recent-list"]').exists()).toBe(false)
  })

  it('se os projetos falharam mostra o erro com "Tentar de novo" e mantém o gráfico', async () => {
    useSessionsStore(pinia).loaded = false
    useSessionsStore(pinia).setForProject(1, [])
    useProjectsStore(pinia).loadError = 'Servidor caiu.'
    const { wrapper } = await mountDashboard()
    expect(wrapper.find('[data-test="load-error"]').text()).toContain('Servidor caiu.')
    expect(wrapper.find('[data-test="now-empty"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="stat-waiting"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="activity-empty"]').exists()).toBe(true)
    await wrapper.find('[data-test="load-retry"]').trigger('click')
    expect(loadEverything).toHaveBeenCalledTimes(1)
  })
})

describe('Dashboard: bloco Agora limitado', () => {
  const waitingSession = (id: number, over: Record<string, unknown> = {}) =>
    makeSession({ session_id: `x${id}`, title: `Espera ${id}`, display_state: 'waiting', state: 'closed', last_activity_at: now - id, ...over })

  it('com mais de 6 ativas mostra 6 cartões e o link para a Inbox', async () => {
    useSessionsStore(pinia).setForProject(1, Array.from({ length: 8 }, (_, i) => waitingSession(i)))
    const { wrapper } = await mountDashboard()
    expect(wrapper.findAll('[data-test="now-card"]')).toHaveLength(6)
    const more = wrapper.find('[data-test="now-more"]')
    expect(more.text()).toBe('Ver todas as 8 na Inbox')
    expect(more.attributes('href')).toBe('/inbox?aba=todas')
  })

  it('com 6 ou menos não mostra o link', async () => {
    useSessionsStore(pinia).setForProject(1, Array.from({ length: 6 }, (_, i) => waitingSession(i)))
    const { wrapper } = await mountDashboard()
    expect(wrapper.findAll('[data-test="now-card"]')).toHaveLength(6)
    expect(wrapper.find('[data-test="now-more"]').exists()).toBe(false)
  })

  it('ordena: pedido pendente, depois em execução, depois "Sua vez"; cada grupo do mais novo ao mais antigo', async () => {
    useSessionsStore(pinia).setForProject(1, [
      waitingSession(1, { session_id: 'vez', title: 'Sua vez', last_activity_at: now }),
      makeSession({ session_id: 'run-old', title: 'Rodando antiga', display_state: 'running', state: 'running', last_activity_at: now - 50 }),
      makeSession({ session_id: 'run-new', title: 'Rodando nova', display_state: 'running', state: 'running', last_activity_at: now - 5 }),
      waitingSession(2, { session_id: 'ask-old', title: 'Pede antiga', awaiting_decision: true, pending_kind: 'tool', last_activity_at: now - 1000 }),
      waitingSession(3, { session_id: 'ask-kind', title: 'Pede pergunta', pending_kind: 'question', last_activity_at: now - 2000 }),
    ])
    const { wrapper } = await mountDashboard()
    const titles = wrapper.findAll('[data-test="now-card"]').map((c) => c.find('a').text())
    expect(titles).toEqual(['Pede antiga', 'Pede pergunta', 'Rodando nova', 'Rodando antiga', 'Sua vez'])
  })

  it('"Aguardando você" conta só as esperas que precisam de você', async () => {
    useSessionsStore(pinia).setForProject(1, [
      ...Array.from({ length: 5 }, (_, i) => makeSession({ session_id: `r${i}`, display_state: 'running', state: 'running', last_activity_at: now - i })),
      waitingSession(0),
      waitingSession(1, { unread: true }),
      waitingSession(2, { pending_kind: 'plan' }),
    ])
    const { wrapper } = await mountDashboard()
    expect(wrapper.find('[data-test="stat-running"] span').text()).toBe('5')
    expect(wrapper.find('[data-test="stat-waiting"] span').text()).toBe('2')
  })
})

describe('Dashboard com marcações', () => {
  it('"Aguardando você" ignora em espera e bloqueada sem pedido, e há card Para revisar', async () => {
    useSessionsStore(pinia).setForProject(1, [
      makeSession({ session_id: 'livre', unread: true, last_activity_at: now }),
      makeSession({ session_id: 'espera', unread: true, mark: 'on_hold', last_activity_at: now }),
      makeSession({ session_id: 'blq', mark: 'blocked', state: 'awaiting_decision', awaiting_decision: true, pending_kind: 'question', last_activity_at: now }),
      makeSession({ session_id: 'rev1', mark: 'review', last_activity_at: now }),
      makeSession({ session_id: 'rev2', mark: 'review', last_activity_at: now }),
    ])
    const { wrapper } = await mountDashboard()
    expect(wrapper.find('[data-test="stat-waiting"]').text()).toContain('2')
    const review = wrapper.find('[data-test="stat-review"]')
    expect(review.text()).toContain('2')
    expect(review.text()).toContain('Para revisar')
    expect(review.attributes('href')).toBe('/inbox?aba=para-revisar')
  })

  it('cards de Agora não mostram sessões em Depois', async () => {
    useSessionsStore(pinia).setForProject(1, [
      makeSession({ session_id: 'a', title: 'Comum', display_state: 'running', state: 'running', last_activity_at: now }),
      makeSession({ session_id: 'b', title: 'Guardada', display_state: 'running', state: 'running', mark: 'on_hold', last_activity_at: now }),
    ])
    const { wrapper } = await mountDashboard()
    expect(wrapper.findAll('[data-test="now-card"]').map((c) => c.find('a').text())).toEqual(['Comum'])
    expect(wrapper.find('[data-test="stat-running"]').text()).toContain('2')
  })
})
