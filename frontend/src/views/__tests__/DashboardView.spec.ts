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

enableAutoUnmount(afterEach)
let pinia: Pinia
const now = Math.floor(Date.now() / 1000)

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  const projects = useProjectsStore(pinia)
  projects.projects = [makeProject({ id: 1, name: 'a' }), makeProject({ id: 2, name: 'b', path: '/b' })]
  projects.loaded = true
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
    expect(cards.map((c) => c.find('a').text())).toEqual(['Rodando', 'Pede'])
    expect(cards[0]!.text()).toContain('Edit main.py')
    expect(cards[1]!.text()).toContain('Pede permissão: Bash')
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
    expect(wrapper.find('[data-test="stat-finished-today"]').attributes('href')).toBe('/sessions?estado=finalizadas')
    expect(wrapper.find('[data-test="stat-projects-changes"]').text()).toContain('1')
  })

  it('falha do gráfico não derruba o resto e pode tentar de novo', async () => {
    let calls = 0
    const { wrapper } = await mountDashboard(() => (++calls === 1 ? jsonResponse({ detail: 'x' }, 500) : jsonResponse([])))

    expect(wrapper.find('[data-test="activity-error"]').text()).toContain('Não foi possível carregar a atividade')
    expect(wrapper.findAll('[data-test="now-card"]')).toHaveLength(2)
    await wrapper.find('[data-test="activity-retry"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-test="activity-empty"]').exists()).toBe(true)
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
})
