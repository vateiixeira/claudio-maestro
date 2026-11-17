import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import DashboardView from '../DashboardView.vue'
import { createAppRouter } from '../../router'
import { useGitStore } from '../../stores/git'
import { useProjectsStore } from '../../stores/projects'
import { useSessionsStore } from '../../stores/sessions'
import { useUsageStore } from '../../stores/usage'
import { jsonResponse, makeGitRepo, makeProject, makeSession, routeFetch } from '../../test/factories'
import type { UsageSnapshot } from '../../types/api'

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
  projects.projects.push(makeProject({ id: 99, name: 'Sem projeto', path: '/home/vi/.local/share/claudio-maestro/scratch', kind: 'scratch', position: 99 }))
  useGitStore(pinia).set(99, [makeGitRepo({ path: '/scratch', changed: { staged: 1, unstaged: 0, untracked: 0 } })])
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

async function mountDashboard() {
  const fetch = routeFetch({ 'POST /api/sessions/w/prompts/p1': () => jsonResponse(undefined, 204) })
  vi.stubGlobal('fetch', fetch)
  const router = createAppRouter(createMemoryHistory())
  const wrapper = mount(DashboardView, { global: { plugins: [pinia, router] } })
  await flushPromises()
  return { wrapper, fetch }
}

const nowTitles = (wrapper: Awaited<ReturnType<typeof mountDashboard>>['wrapper']) =>
  wrapper.findAll('[data-test="now-row"]').map((r) => r.get('[data-test="now-row-link"]').text())

describe('Painel', () => {
  it('o título da página é Painel', async () => {
    const { wrapper } = await mountDashboard()
    expect(wrapper.get('h1').text()).toBe('Painel')
  })

  it('não consulta mais a atividade por dia', async () => {
    const { fetch } = await mountDashboard()
    expect(fetch.mock.calls.some(([url]) => String(url).includes('/api/activity'))).toBe(false)
  })

  it('mostra uma linha por conversa ativa, com a última ação', async () => {
    const { wrapper } = await mountDashboard()
    expect(nowTitles(wrapper)).toEqual(['Pede', 'Rodando'])
    expect(wrapper.findAll('[data-test="now-row"]')[1]!.text()).toContain('Edit main.py')
  })

  it('permite pela linha', async () => {
    const { wrapper, fetch } = await mountDashboard()
    await wrapper.find('[data-test="now-allow"]').trigger('click')
    await flushPromises()
    const call = fetch.mock.calls.find(([url]) => url === '/api/sessions/w/prompts/p1')!
    expect(JSON.parse(call[1]!.body as string)).toEqual({ decision: 'allow_once' })
  })

  it('sem conversas ativas mostra o aviso', async () => {
    useSessionsStore(pinia).setForProject(1, [])
    const { wrapper } = await mountDashboard()
    expect(wrapper.find('[data-test="now-empty"]').text()).toBe('Nenhuma conversa ativa agora.')
  })

  it('enquanto as conversas carregam mostra "Carregando…" e nenhum zero nem aviso de vazio', async () => {
    useSessionsStore(pinia).loaded = false
    useSessionsStore(pinia).setForProject(1, [])
    const { wrapper } = await mountDashboard()
    expect(wrapper.find('[data-test="load-loading"]').text()).toBe('Carregando…')
    expect(wrapper.find('[data-test="now-empty"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="stat-running"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="finished-today"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="changes-list"]').exists()).toBe(false)
  })

  it('se os projetos falharam mostra o erro com "Tentar de novo"', async () => {
    useSessionsStore(pinia).loaded = false
    useSessionsStore(pinia).setForProject(1, [])
    useProjectsStore(pinia).loadError = 'Servidor caiu.'
    const { wrapper } = await mountDashboard()
    expect(wrapper.find('[data-test="load-error"]').text()).toContain('Servidor caiu.')
    expect(wrapper.find('[data-test="now-empty"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="stat-waiting"]').exists()).toBe(false)
    await wrapper.find('[data-test="load-retry"]').trigger('click')
    expect(loadEverything).toHaveBeenCalledTimes(1)
  })
})

describe('Painel: uso da semana', () => {
  const WEEKDAYS = ['dom', 'seg', 'ter', 'qua', 'qui', 'sex', 'sáb']
  function resetsInTwoDays() {
    const d = new Date()
    d.setDate(d.getDate() + 2)
    d.setHours(19, 0, 0, 0)
    return { at: d.getTime() / 1000, label: `${WEEKDAYS[d.getDay()]} 19:00` }
  }
  const snapshot = (over: Partial<UsageSnapshot> = {}): UsageSnapshot => ({ enabled: true, limits: [], fetched_at: now, error: null, plan: null, ...over })

  it('mostra o medidor da semana com a porcentagem e quando renova', async () => {
    const reset = resetsInTwoDays()
    useUsageStore(pinia).snapshot = snapshot({ limits: [{ kind: 'weekly_all', label: 'Semana', percent: 19, severity: 'normal', resets_at: reset.at }] })
    const { wrapper } = await mountDashboard()
    const meter = wrapper.get('[data-test="dashboard-usage"]')
    expect(meter.attributes('role')).toBe('meter')
    expect(meter.attributes('aria-valuenow')).toBe('19')
    expect(meter.text()).toContain(`19% · renova ${reset.label}`)
  })

  it('mostra o plano ao lado', async () => {
    useUsageStore(pinia).snapshot = snapshot({ plan: 'Max', limits: [{ kind: 'weekly_all', label: 'Semana', percent: 19, severity: 'normal', resets_at: null }] })
    const { wrapper } = await mountDashboard()
    expect(wrapper.get('[data-test="dashboard-plan"]').text()).toBe('Max')
    expect(wrapper.get('[data-test="dashboard-usage"]').text()).toContain('19%')
    expect(wrapper.get('[data-test="dashboard-usage"]').text()).not.toContain('renova')
  })

  it('sem o limite da semana não mostra medidor nem plano', async () => {
    useUsageStore(pinia).snapshot = snapshot({ plan: 'Max', limits: [{ kind: 'session', label: 'Sessão', percent: 5, severity: 'normal', resets_at: null }] })
    const { wrapper } = await mountDashboard()
    expect(wrapper.find('[data-test="dashboard-usage"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="dashboard-plan"]').exists()).toBe(false)
  })

  it('sem leitura de uso nenhum dos dois aparece', async () => {
    const { wrapper } = await mountDashboard()
    expect(wrapper.find('[data-test="dashboard-usage"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="dashboard-plan"]').exists()).toBe(false)
  })
})

describe('Painel: números', () => {
  it('mostra os números com links', async () => {
    const { wrapper } = await mountDashboard()
    expect(wrapper.find('[data-test="stat-running"]').text()).toContain('1')
    expect(wrapper.find('[data-test="stat-running"]').attributes('href')).toBe('/inbox?aba=em-execucao')
    expect(wrapper.find('[data-test="stat-waiting"]').text()).toContain('1')
    expect(wrapper.find('[data-test="stat-waiting"]').attributes('href')).toBe('/inbox?aba=pede-voce')
    expect(wrapper.find('[data-test="stat-finished-today"]').text()).toContain('1')
    expect(wrapper.find('[data-test="stat-finished-today"]').attributes('href')).toBe('/entregas')
    expect(wrapper.find('[data-test="stat-projects-changes"]').text()).toContain('1')
  })

  it('número zero fica em tom discreto', async () => {
    useSessionsStore(pinia).setForProject(1, [])
    const { wrapper } = await mountDashboard()
    expect(wrapper.get('[data-test="stat-running"] span').classes()).toContain('text-fg-subtle')
    expect(wrapper.get('[data-test="stat-review"] span').classes()).toContain('text-fg-subtle')
    expect(wrapper.get('[data-test="stat-finished-today"] span').classes()).toContain('text-fg-subtle')
  })

  it('o ícone de "Em execução" não gira nem fica verde com zero', async () => {
    useSessionsStore(pinia).setForProject(1, [])
    const { wrapper } = await mountDashboard()
    const zero = wrapper.get('[data-test="stat-running"] [data-shape="spinner"]')
    expect(zero.attributes('data-quiet')).toBe('true')
    expect(zero.get('svg').classes()).not.toContain('motion-safe:animate-spin')
  })

  it('o ícone de "Em execução" gira e fica verde com contagem maior que zero', async () => {
    const { wrapper } = await mountDashboard()
    const icon = wrapper.get('[data-test="stat-running"] [data-shape="spinner"]')
    expect(icon.attributes('data-quiet')).toBeUndefined()
    expect(icon.get('svg').classes()).toContain('stroke-primary')
  })

  it('número maior que zero fica em tom normal', async () => {
    const { wrapper } = await mountDashboard()
    expect(wrapper.get('[data-test="stat-running"] span').classes()).not.toContain('text-fg-subtle')
  })

  it('"Aguardando você" conta só as esperas que precisam de você', async () => {
    const waitingSession = (id: number, over: Record<string, unknown> = {}) =>
      makeSession({ session_id: `x${id}`, title: `Espera ${id}`, display_state: 'waiting', state: 'closed', last_activity_at: now - id, ...over })
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

  it('uma conversa reaberta com finished_at antigo não conta como finalizada hoje', async () => {
    useSessionsStore(pinia).setForProject(1, [
      makeSession({ session_id: 'f', title: 'Feita', display_state: 'finished', finished: true, finished_at: now, last_activity_at: now }),
      makeSession({ session_id: 're', title: 'Reaberta', display_state: 'running', finished: false, finished_at: now, last_activity_at: now }),
    ])
    const { wrapper } = await mountDashboard()
    expect(wrapper.find('[data-test="stat-finished-today"] span').text()).toBe('1')
    expect(wrapper.findAll('[data-test="finished-row"]')).toHaveLength(1)
  })

  it('"Aguardando você" ignora em espera e bloqueada sem pedido, e há número Para revisar', async () => {
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
})

describe('Painel: Agora', () => {
  const waitingSession = (id: number, over: Record<string, unknown> = {}) =>
    makeSession({ session_id: `x${id}`, title: `Espera ${id}`, display_state: 'waiting', state: 'closed', last_activity_at: now - id, ...over })

  it('o cabeçalho diz quantas estão em execução', async () => {
    useSessionsStore(pinia).setForProject(1, Array.from({ length: 3 }, (_, i) => makeSession({ session_id: `r${i}`, display_state: 'running', state: 'running', last_activity_at: now - i })))
    const { wrapper } = await mountDashboard()
    expect(wrapper.get('[data-test="now-running-count"]').text()).toBe('3 em execução')
  })

  it('com mais de 6 ativas mostra 6 linhas e o link para a Inbox', async () => {
    useSessionsStore(pinia).setForProject(1, Array.from({ length: 8 }, (_, i) => waitingSession(i)))
    const { wrapper } = await mountDashboard()
    expect(wrapper.findAll('[data-test="now-row"]')).toHaveLength(6)
    const more = wrapper.find('[data-test="now-more"]')
    expect(more.text()).toBe('Ver as 8 na Inbox')
    expect(more.attributes('href')).toBe('/inbox?aba=todas')
  })

  it('com 6 ou menos não mostra o link', async () => {
    useSessionsStore(pinia).setForProject(1, Array.from({ length: 6 }, (_, i) => waitingSession(i)))
    const { wrapper } = await mountDashboard()
    expect(wrapper.findAll('[data-test="now-row"]')).toHaveLength(6)
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
    expect(nowTitles(wrapper)).toEqual(['Pede antiga', 'Pede pergunta', 'Rodando nova', 'Rodando antiga', 'Sua vez'])
  })

  it('não mostra conversas em Depois nem descartadas, mas as em Depois contam como em execução', async () => {
    useSessionsStore(pinia).setForProject(1, [
      makeSession({ session_id: 'a', title: 'Comum', display_state: 'running', state: 'running', last_activity_at: now }),
      makeSession({ session_id: 'b', title: 'Guardada', display_state: 'running', state: 'running', mark: 'on_hold', last_activity_at: now }),
      makeSession({ session_id: 'c', title: 'Descartada', display_state: 'running', state: 'running', mark: 'discarded', last_activity_at: now }),
    ])
    const { wrapper } = await mountDashboard()
    expect(nowTitles(wrapper)).toEqual(['Comum'])
    expect(wrapper.find('[data-test="stat-running"]').text()).toContain('2')
    expect(wrapper.text()).not.toContain('Descartada')
  })
})

describe('Painel: Finalizadas hoje', () => {
  it('lista as finalizadas desde a meia-noite, da mais recente para a mais antiga, cada uma com o projeto', async () => {
    useSessionsStore(pinia).setForProject(1, [
      makeSession({ session_id: 'f1', title: 'Primeira', display_state: 'finished', finished: true, finished_at: now - 600, last_activity_at: now - 600 }),
      makeSession({ session_id: 'f2', title: 'Segunda', display_state: 'finished', finished: true, finished_at: now - 60, last_activity_at: now - 60 }),
      makeSession({ session_id: 'old', title: 'Ontem', display_state: 'finished', finished: true, finished_at: now - 2 * 86400, last_activity_at: now - 2 * 86400 }),
    ])
    const { wrapper } = await mountDashboard()
    const rows = wrapper.findAll('[data-test="finished-row"]')
    expect(rows.map((r) => r.get('[data-test="finished-row-link"]').text())).toEqual(['Segunda', 'Primeira'])
    expect(rows[0]!.get('[data-test="project-tag"]').text()).toBe('a')
    expect(wrapper.get('[data-test="finished-today"]').text()).toContain('Finalizadas hoje')
  })

  it('sem nenhuma diz que nada foi finalizado hoje', async () => {
    useSessionsStore(pinia).setForProject(1, [])
    const { wrapper } = await mountDashboard()
    expect(wrapper.findAll('[data-test="finished-row"]')).toHaveLength(0)
    expect(wrapper.get('[data-test="finished-today"]').text()).toContain('Nada finalizado hoje ainda.')
  })

  it('com mais de 8 mostra 8 e o link para as Entregas', async () => {
    useSessionsStore(pinia).setForProject(1, Array.from({ length: 10 }, (_, i) =>
      makeSession({ session_id: `f${i}`, title: `Feita ${i}`, display_state: 'finished', finished: true, finished_at: now - i, last_activity_at: now - i })))
    const { wrapper } = await mountDashboard()
    expect(wrapper.findAll('[data-test="finished-row"]')).toHaveLength(8)
    const more = wrapper.get('[data-test="finished-more"]')
    expect(more.text()).toBe('Mais 2 em Entregas')
    expect(more.attributes('href')).toBe('/entregas')
  })
})

describe('Painel: Projetos com alterações', () => {
  function setProjects(counts: number[]) {
    const projects = useProjectsStore(pinia)
    projects.projects = counts.map((_, i) => makeProject({ id: i + 1, name: `proj-${i + 1}`, path: `/p${i + 1}`, position: i }))
    counts.forEach((n, i) => useGitStore(pinia).set(i + 1, [makeGitRepo({ path: `/p${i + 1}`, branch: `ramo-${i + 1}`, changed: { staged: 0, unstaged: n, untracked: 0 } })]))
  }

  it('lista os projetos com alterações do maior para o menor, com barra proporcional e destino na visão git', async () => {
    setProjects([7, 0, 14])
    const { wrapper } = await mountDashboard()
    const rows = wrapper.findAll('[data-test="changes-row"]')
    expect(rows).toHaveLength(2)
    expect(rows[0]!.text()).toContain('proj-3')
    expect(rows[0]!.text()).toContain('14 arquivos')
    expect(rows[0]!.text()).toContain('ramo-3')
    expect(rows[0]!.get('[data-test="changes-bar"]').attributes('style')).toContain('width: 100%')
    expect(rows[0]!.attributes('href')).toBe('/projects/3?visao=git')
    expect(rows[1]!.text()).toContain('proj-1')
    expect(rows[1]!.text()).toContain('7 arquivos')
    expect(rows[1]!.get('[data-test="changes-bar"]').attributes('style')).toContain('width: 50%')
    expect(rows[1]!.attributes('href')).toBe('/projects/1?visao=git')
  })

  it('um arquivo fica no singular', async () => {
    setProjects([1])
    const { wrapper } = await mountDashboard()
    expect(wrapper.get('[data-test="changes-row"]').text()).toContain('1 arquivo')
    expect(wrapper.get('[data-test="changes-row"]').text()).not.toContain('1 arquivos')
  })

  it('o projeto embutido não entra', async () => {
    const { wrapper } = await mountDashboard()
    expect(wrapper.get('[data-test="changes-list"]').text()).not.toContain('Sem projeto')
    expect(wrapper.findAll('[data-test="changes-row"]')).toHaveLength(1)
    expect(wrapper.find('[data-test="stat-projects-changes"]').text()).toContain('1')
  })

  it('mostra 4 linhas e resume o resto, com os sem alteração', async () => {
    setProjects([10, 9, 8, 7, 6, 5, 0, 0, 0])
    const { wrapper } = await mountDashboard()
    expect(wrapper.findAll('[data-test="changes-row"]')).toHaveLength(4)
    expect(wrapper.get('[data-test="changes-more"]').text()).toBe('Mais 2 com alterações · 3 projetos sem alterações ficam fora da lista')
    expect(wrapper.get('[data-test="stat-projects-changes"]').text()).toContain('6')
  })

  it('um só projeto sem alterações fica no singular', async () => {
    setProjects([3, 0])
    const { wrapper } = await mountDashboard()
    expect(wrapper.get('[data-test="changes-more"]').text()).toBe('1 projeto sem alterações fica fora da lista')
  })

  it('sem nada fora da lista não mostra o resumo', async () => {
    setProjects([3, 2])
    const { wrapper } = await mountDashboard()
    expect(wrapper.find('[data-test="changes-more"]').exists()).toBe(false)
  })

  it('só alterações escondidas: "Mais N com alterações" sem a parte dos limpos', async () => {
    setProjects([9, 8, 7, 6, 5])
    const { wrapper } = await mountDashboard()
    expect(wrapper.get('[data-test="changes-more"]').text()).toBe('Mais 1 com alterações')
  })

  it('sem projeto alterado diz que não há alterações', async () => {
    setProjects([0, 0])
    const { wrapper } = await mountDashboard()
    expect(wrapper.findAll('[data-test="changes-row"]')).toHaveLength(0)
    expect(wrapper.get('[data-test="changes-list"]').text()).toContain('Nenhum projeto com alterações.')
    expect(wrapper.get('[data-test="changes-more"]').text()).toBe('2 projetos sem alterações ficam fora da lista')
  })

  it('o número Projetos com alterações rola até a lista', async () => {
    const { wrapper } = await mountDashboard()
    document.body.appendChild(wrapper.element)
    const scrollIntoView = vi.fn()
    const list = wrapper.get('[data-test="changes-list"]').element as HTMLElement
    list.scrollIntoView = scrollIntoView
    await wrapper.get('[data-test="stat-projects-changes"]').trigger('click')
    expect(scrollIntoView).toHaveBeenCalled()
  })
})
