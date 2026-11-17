import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import StartView from '../StartView.vue'
import { createAppRouter } from '../../router'
import { goalDrafts } from '../../goalDrafts'
import { localDay } from '../../deliveries'
import { useDeliveriesStore } from '../../stores/deliveries'
import { useOrgStore } from '../../stores/org'
import { useProjectsStore } from '../../stores/projects'
import { useSessionsStore } from '../../stores/sessions'
import { jsonResponse, makeAgent, makeDecision, makeDelivery, makeNotice, makeProject, makeSession, routeFetch } from '../../test/factories'
import type { DeliveriesDay, Delivery } from '../../types/api'

enableAutoUnmount(afterEach)
let pinia: Pinia

const TODAY = localDay()
const DELIVERIES_URL = `GET /api/deliveries?date=${TODAY}`
const NOW = Math.floor(Date.now() / 1000)

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  for (const key of Object.keys(goalDrafts)) delete goalDrafts[key]
  const projects = useProjectsStore(pinia)
  projects.projects = [makeProject({ id: 2, name: 'Loja' }), makeProject({ id: 3, name: 'API', path: '/api' })]
  projects.loaded = true
  useOrgStore(pinia).agents = [makeAgent({ id: 11, name: 'CTO da Loja', project_id: 2, slug: 'cto' })]
  useOrgStore(pinia).loaded = true
})
afterEach(() => vi.unstubAllGlobals())

function day(deliveries: Delivery[] = [], overrides: Partial<DeliveriesDay> = {}): DeliveriesDay {
  return { date: TODAY, agent_enabled: false, deliveries, in_progress: [], prev_day: null, next_day: null, ...overrides }
}

function routes(extra: Record<string, (init?: RequestInit) => Response | Promise<Response>> = {}) {
  return routeFetch({
    [DELIVERIES_URL]: () => jsonResponse(day()),
    ...extra,
  })
}

async function mountStart(path = '/inicio') {
  const router = createAppRouter(createMemoryHistory())
  await router.push(path)
  const wrapper = mount(StartView, { global: { plugins: [pinia, router] } })
  await flushPromises()
  return { wrapper, router }
}

/** Today at hh:mm, local time, in seconds. */
function todayAt(hour: number, minute = 0): number {
  const d = new Date()
  return Math.floor(new Date(d.getFullYear(), d.getMonth(), d.getDate(), hour, minute).getTime() / 1000)
}

describe('objetivo', () => {
  it('entrega ao topo do projeto e leva ao painel dele', async () => {
    const fetch = routes({
      'POST /api/agents/11/main': () => jsonResponse({ session_id: 'main-11' }),
      'POST /api/sessions/main-11/messages': () => jsonResponse({ state: 'running' }),
    })
    vi.stubGlobal('fetch', fetch)
    const { wrapper, router } = await mountStart()
    await wrapper.get('[data-test="goal-project-other"]').setValue('2')
    expect(wrapper.get('[data-test="goal-submit"]').text()).toContain('CTO da Loja')
    await wrapper.get('textarea').setValue('Investigar sem publicar')
    await wrapper.get('form').trigger('submit')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(fetch.mock.calls.filter((c) => c[0] === '/api/agents/11/main')).toHaveLength(1)
    const messages = fetch.mock.calls.filter((c) => c[0] === '/api/sessions/main-11/messages')
    expect(messages).toHaveLength(1)
    expect(JSON.parse(String(messages[0]?.[1]?.body))).toEqual({ text: 'Investigar sem publicar' })
    expect(router.currentRoute.value.path).toBe('/agentes/2')
    expect(router.currentRoute.value.query.agente).toBe('11')
    expect(goalDrafts['2']).toBe('')
  })

  it('sem topo orienta a criar', async () => {
    vi.stubGlobal('fetch', routes())
    const { wrapper } = await mountStart()
    await wrapper.get('[data-test="goal-project-other"]').setValue('3')
    await wrapper.get('textarea').setValue('Algo')
    const note = wrapper.get('[data-test="goal-no-top"]')
    expect(note.text()).toContain('Este projeto ainda não tem um CTO. Crie um na Organização.')
    expect(note.get('a').attributes('href')).toBe('/agentes/3')
    expect(wrapper.get('[data-test="goal-submit"]').attributes('disabled')).toBeDefined()
  })

  it('exige projeto e texto; falha no envio preserva o objetivo e mostra o erro', async () => {
    const fetch = routes({
      'POST /api/agents/11/main': () => jsonResponse({ session_id: 'main-11' }),
      'POST /api/sessions/main-11/messages': () => jsonResponse({ detail: 'Sem espaço.' }, 500),
    })
    vi.stubGlobal('fetch', fetch)
    const { wrapper, router } = await mountStart()
    expect(wrapper.get('[data-test="goal-submit"]').attributes('disabled')).toBeDefined()
    await wrapper.get('textarea').setValue('Meu objetivo')
    expect(wrapper.get('[data-test="goal-submit"]').attributes('disabled')).toBeDefined()
    await wrapper.get('[data-test="goal-project-other"]').setValue('2')
    expect(wrapper.get('[data-test="goal-submit"]').attributes('disabled')).toBeUndefined()
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('Sem espaço.')
    expect(wrapper.get('[role="alert"]').text()).toContain('O objetivo foi preservado')
    expect((wrapper.get('textarea').element as HTMLTextAreaElement).value).toBe('Meu objetivo')
    expect(router.currentRoute.value.path).toBe('/inicio')
  })

  it('mantém os rascunhos separados por projeto', async () => {
    vi.stubGlobal('fetch', routes())
    const { wrapper } = await mountStart()
    await wrapper.get('[data-test="goal-project-other"]').setValue('2')
    await wrapper.get('textarea').setValue('Objetivo da loja')
    await wrapper.get('[data-test="goal-project-other"]').setValue('3')
    expect((wrapper.get('textarea').element as HTMLTextAreaElement).value).toBe('')
    await wrapper.get('textarea').setValue('Objetivo da API')
    await wrapper.get('[data-test="goal-project-other"]').setValue('2')
    expect((wrapper.get('textarea').element as HTMLTextAreaElement).value).toBe('Objetivo da loja')
  })

  it('não tem mais o aviso do despacho desligado', async () => {
    vi.stubGlobal('fetch', routes())
    const { wrapper } = await mountStart()
    expect(wrapper.text()).not.toContain('despacho')
  })
})


describe('projeto do objetivo', () => {
  function withActivity() {
    useProjectsStore(pinia).projects = [
      makeProject({ id: 2, name: 'Loja' }),
      makeProject({ id: 3, name: 'API', path: '/api' }),
      makeProject({ id: 4, name: 'Blog', path: '/blog' }),
      makeProject({ id: 5, name: 'Docs', path: '/docs' }),
      makeProject({ id: 6, name: 'Fora do ar', path: '/off', available: false }),
    ]
    const sessions = useSessionsStore(pinia)
    sessions.setForProject(2, [makeSession({ session_id: 'a', project_id: 2, last_activity_at: NOW - 300 })])
    sessions.setForProject(3, [makeSession({ session_id: 'b', project_id: 3, last_activity_at: NOW - 200 })])
    sessions.setForProject(4, [makeSession({ session_id: 'c', project_id: 4, last_activity_at: NOW - 900 })])
    sessions.setForProject(5, [makeSession({ session_id: 'd', project_id: 5, last_activity_at: NOW - 100 })])
    sessions.setForProject(6, [makeSession({ session_id: 'e', project_id: 6, last_activity_at: NOW - 10 })])
  }

  it('mostra no máximo três chips, dos projetos disponíveis com a conversa mais recente', async () => {
    withActivity()
    vi.stubGlobal('fetch', routes())
    const { wrapper } = await mountStart()
    const chips = wrapper.findAll('[data-test="goal-project"]')
    expect(chips.map((c) => c.text())).toEqual(['Docs', 'API', 'Loja'])
    expect(chips.map((c) => c.attributes('data-id'))).toEqual(['5', '3', '2'])
    expect(chips.every((c) => c.attributes('aria-pressed') === 'false')).toBe(true)
  })

  it('sem conversas, usa a ordem dos projetos', async () => {
    vi.stubGlobal('fetch', routes())
    const { wrapper } = await mountStart()
    expect(wrapper.findAll('[data-test="goal-project"]').map((c) => c.text())).toEqual(['Loja', 'API'])
  })

  it('clicar num chip liga o projeto e põe no endereço; clicar de novo desliga', async () => {
    withActivity()
    vi.stubGlobal('fetch', routes())
    const { wrapper, router } = await mountStart()
    await wrapper.get('[data-test="goal-project"][data-id="3"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-test="goal-project"][data-id="3"]').attributes('aria-pressed')).toBe('true')
    expect(router.currentRoute.value.query.projeto).toBe('3')
    await wrapper.get('[data-test="goal-project"][data-id="3"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-test="goal-project"][data-id="3"]').attributes('aria-pressed')).toBe('false')
    expect(router.currentRoute.value.query.projeto).toBeUndefined()
  })

  it('escolher outro projeto o mostra como chip ligado, sem passar de três', async () => {
    withActivity()
    vi.stubGlobal('fetch', routes())
    const { wrapper, router } = await mountStart()
    await wrapper.get('[data-test="goal-project-other"]').setValue('4')
    await flushPromises()
    const chips = wrapper.findAll('[data-test="goal-project"]')
    expect(chips).toHaveLength(3)
    const on = chips.filter((c) => c.attributes('aria-pressed') === 'true')
    expect(on.map((c) => c.text())).toEqual(['Blog'])
    expect(router.currentRoute.value.query.projeto).toBe('4')
    expect((wrapper.get('[data-test="goal-project-other"]').element as HTMLSelectElement).value).toBe('')
  })

  it('o "Outro…" lista todos os projetos e o endereço com ?projeto= já abre ligado', async () => {
    withActivity()
    vi.stubGlobal('fetch', routes())
    const { wrapper } = await mountStart('/inicio?projeto=3')
    const other = wrapper.get('[data-test="goal-project-other"]')
    expect(other.attributes('aria-label')).toBe('Projeto do objetivo')
    expect(other.findAll('option').map((o) => o.text())).toEqual(expect.arrayContaining(['Loja', 'API', 'Blog', 'Docs']))
    expect(wrapper.get('[data-test="goal-project"][data-id="3"]').attributes('aria-pressed')).toBe('true')
  })
})

describe('envio pelo teclado', () => {
  async function ready() {
    const fetch = routes({
      'POST /api/agents/11/main': () => jsonResponse({ session_id: 'main-11' }),
      'POST /api/sessions/main-11/messages': () => jsonResponse({ state: 'running' }),
    })
    vi.stubGlobal('fetch', fetch)
    const { wrapper } = await mountStart('/inicio?projeto=2')
    await wrapper.get('textarea').setValue('Meu objetivo')
    return { wrapper, fetch }
  }

  it('Ctrl+Enter envia uma vez', async () => {
    const { wrapper, fetch } = await ready()
    await wrapper.get('textarea').trigger('keydown', { key: 'Enter', ctrlKey: true })
    await wrapper.get('textarea').trigger('keydown', { key: 'Enter', ctrlKey: true })
    await flushPromises()
    expect(fetch.mock.calls.filter((c) => c[0] === '/api/sessions/main-11/messages')).toHaveLength(1)
  })

  it('Enter sozinho não envia', async () => {
    const { wrapper, fetch } = await ready()
    await wrapper.get('textarea').trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(fetch.mock.calls.filter((c) => c[0] === '/api/agents/11/main')).toHaveLength(0)
  })

  it('mostra a dica Ctrl Enter', async () => {
    vi.stubGlobal('fetch', routes())
    const { wrapper } = await mountStart()
    expect(wrapper.text()).toContain('Ctrl')
    expect(wrapper.text()).toContain('Enter')
  })
})

describe('cabeçalho', () => {
  it('"Ver tarefas" leva às tarefas e o título é o de sempre', async () => {
    vi.stubGlobal('fetch', routes())
    const { wrapper } = await mountStart()
    expect(wrapper.get('h1').text()).toBe('O que vamos resolver?')
    const link = wrapper.findAll('a').find((a) => a.text().includes('Ver tarefas'))
    expect(link?.attributes('href')).toBe('/tarefas')
  })

  it('não chama a API de tarefas', async () => {
    const fetch = routes()
    vi.stubGlobal('fetch', fetch)
    await mountStart()
    expect(fetch.mock.calls.filter((c) => String(c[0]).startsWith('/api/tasks'))).toHaveLength(0)
  })
})

describe('Com você', () => {
  function seed() {
    const org = useOrgStore(pinia)
    org.agents = [
      makeAgent({ id: 11, name: 'CTO da Loja', project_id: 2, slug: 'cto' }),
      makeAgent({ id: 21, name: 'Agente de suporte', project_id: 2, slug: 'sup' }),
      makeAgent({ id: 22, name: 'Agente de triagem', project_id: 2, slug: 'tri' }),
    ]
    org.notices = [
      makeNotice({ id: 1, agent_id: 22 }), makeNotice({ id: 2, agent_id: 22 }), makeNotice({ id: 3, agent_id: 22 }),
      makeNotice({ id: 4, agent_id: 21 }), makeNotice({ id: 5, agent_id: 21 }),
      makeNotice({ id: 6, agent_id: 21, read_at: NOW }),
    ]
  }

  it('resume as conversas na sua vez e as novidades', async () => {
    seed()
    useSessionsStore(pinia).setForProject(2, [
      makeSession({ session_id: 'a', project_id: 2, unread: true }),
      makeSession({ session_id: 'b', project_id: 2 }),
    ])
    vi.stubGlobal('fetch', routes())
    const { wrapper } = await mountStart()
    const section = wrapper.get('[data-test="start-with-you"]')
    expect(section.get('h2').text()).toBe('Com você')
    expect(section.text()).toContain('2 conversas · 5 novidades')
  })

  it('mostra as novidades por agente, em ordem de contagem, e leva à Inbox', async () => {
    seed()
    vi.stubGlobal('fetch', routes())
    const { wrapper } = await mountStart()
    const notices = wrapper.get('[data-test="start-notices"]')
    expect(notices.text()).toContain('5 novidades dos agentes')
    expect(notices.text()).toContain('Agente de triagem 3 · Agente de suporte 2')
    expect(notices.attributes('href')).toBe('/inbox?aba=novidades')
  })

  it('sem avisos não lidos, a linha de novidades não aparece', async () => {
    seed()
    useOrgStore(pinia).notices = [makeNotice({ id: 9, agent_id: 21, read_at: NOW })]
    vi.stubGlobal('fetch', routes())
    const { wrapper } = await mountStart()
    expect(wrapper.find('[data-test="start-notices"]').exists()).toBe(false)
  })

  it('as decisões pendentes aparecem como cartões dentro da seção', async () => {
    useOrgStore(pinia).decisionsPending = [makeDecision({ id: 5, question: 'Posso publicar?' })]
    vi.stubGlobal('fetch', routes())
    const { wrapper } = await mountStart()
    expect(wrapper.get('[data-test="start-with-you"] [data-test="decision-card"]').text()).toContain('Posso publicar?')
  })

  it('lista as conversas esperando, as que pedem você primeiro, sem as marcadas nem as descartadas', async () => {
    useSessionsStore(pinia).setForProject(2, [
      makeSession({ session_id: 'quiet', project_id: 2, title: 'Só espera', last_activity_at: NOW - 60, closure_verdict: 'incomplete' }),
      makeSession({ session_id: 'asks', project_id: 2, title: 'Pede você', last_activity_at: NOW - 3000, unread: true }),
      makeSession({ session_id: 'rev', project_id: 2, title: 'Para revisar', mark: 'review' }),
      makeSession({ session_id: 'hold', project_id: 2, title: 'Em espera', mark: 'on_hold' }),
      makeSession({ session_id: 'gone', project_id: 2, title: 'Descartada', mark: 'discarded' }),
      makeSession({ session_id: 'run', project_id: 2, title: 'Rodando', display_state: 'running', state: 'running' }),
    ])
    vi.stubGlobal('fetch', routes())
    const { wrapper } = await mountStart()
    const rows = wrapper.findAll('[data-test="start-waiting"]')
    expect(rows.map((r) => r.attributes('href'))).toEqual(['/sessions/asks', '/sessions/quiet'])
    expect(rows[1]!.text()).toContain('Entrega incompleta')
    expect(wrapper.get('[data-test="start-with-you"]').text()).not.toContain('Rodando')
  })

  it('mostra no máximo 8 conversas e um link para o resto', async () => {
    useSessionsStore(pinia).setForProject(2, Array.from({ length: 10 }, (_, i) => makeSession({ session_id: `w${i}`, project_id: 2, title: `Conversa ${i}`, last_activity_at: NOW - i * 60 })))
    vi.stubGlobal('fetch', routes())
    const { wrapper } = await mountStart()
    expect(wrapper.findAll('[data-test="start-waiting"]')).toHaveLength(8)
    const more = wrapper.get('[data-test="start-waiting-more"]')
    expect(more.text()).toBe('Mais 2 conversas')
    expect(more.attributes('href')).toBe('/sessions?estado=sua-vez')
  })

  it('sem nada esperando, diz isso em vez de ficar vazia', async () => {
    vi.stubGlobal('fetch', routes())
    const { wrapper } = await mountStart()
    expect(wrapper.get('[data-test="start-with-you"]').text()).toContain('Nada espera você agora.')
  })
})

describe('Em andamento', () => {
  it('lista uma linha por conversa em execução, com a atividade, e leva ao Painel', async () => {
    useSessionsStore(pinia).setForProject(2, [
      makeSession({ session_id: 'r1', project_id: 2, title: 'Rodando um', display_state: 'running', state: 'running', last_action: 'Bash: npm test' }),
      makeSession({ session_id: 'r2', project_id: 2, title: 'Rodando dois', display_state: 'running', state: 'running', last_action: 'Edit: a.ts' }),
      makeSession({ session_id: 'w', project_id: 2, title: 'Esperando' }),
      makeSession({ session_id: 'gone', project_id: 2, title: 'Descartada rodando', display_state: 'running', state: 'running', mark: 'discarded' }),
    ])
    vi.stubGlobal('fetch', routes())
    const { wrapper } = await mountStart()
    const rows = wrapper.findAll('[data-test="start-running"]')
    expect(rows).toHaveLength(2)
    expect(rows.every((r) => r.find('[data-test="session-activity"]').exists())).toBe(true)
    expect(rows[0]!.attributes('href')).toMatch(/^\/sessions\/r[12]$/)
    const link = wrapper.findAll('a').find((a) => a.text() === 'Ver no Painel')
    expect(link?.attributes('href')).toBe('/dashboard')
    expect(wrapper.get('[data-test="start-running-section"]').text()).toContain('Em andamento')
  })

  it('mostra no máximo 8 e um link para o resto', async () => {
    useSessionsStore(pinia).setForProject(2, Array.from({ length: 9 }, (_, i) => makeSession({ session_id: `r${i}`, project_id: 2, display_state: 'running', state: 'running', last_action: 'Edit: a.ts' })))
    vi.stubGlobal('fetch', routes())
    const { wrapper } = await mountStart()
    expect(wrapper.findAll('[data-test="start-running"]')).toHaveLength(8)
    const more = wrapper.get('[data-test="start-running-more"]')
    expect(more.text()).toBe('Mais 1 em andamento')
    expect(more.attributes('href')).toBe('/dashboard')
  })

  it('sem nenhuma em execução, avisa', async () => {
    vi.stubGlobal('fetch', routes())
    const { wrapper } = await mountStart()
    expect(wrapper.get('[data-test="start-running-section"]').text()).toContain('Nenhuma conversa em execução.')
  })
})

describe('Entregue hoje', () => {
  const seven = () => Array.from({ length: 7 }, (_, i) => makeDelivery({
    id: i + 1,
    title: `Entrega ${i + 1}`,
    finished_at: todayAt(8 + i, 10),
    project_id: i % 2 ? 3 : 2,
    project_name: i % 2 ? 'API' : 'Loja',
    session_id: `s${i + 1}`,
  }))

  it('chama as entregas de hoje ao montar e solta o dia ao desmontar', async () => {
    const fetch = routes()
    vi.stubGlobal('fetch', fetch)
    const { wrapper } = await mountStart()
    expect(fetch.mock.calls.filter((c) => c[0] === `/api/deliveries?date=${TODAY}`)).toHaveLength(1)
    const store = useDeliveriesStore(pinia)
    expect(store.date).toBe(TODAY)
    wrapper.unmount()
    expect(store.date).toBeNull()
  })

  it('mostra as quatro mais recentes em ordem de horário e o link para as demais', async () => {
    vi.stubGlobal('fetch', routes({ [DELIVERIES_URL]: () => jsonResponse(day(seven().reverse())) }))
    const { wrapper } = await mountStart()
    const rows = wrapper.findAll('[data-test="start-delivered"]')
    expect(rows.map((r) => r.text())).toEqual([
      expect.stringContaining('Entrega 4'), expect.stringContaining('Entrega 5'), expect.stringContaining('Entrega 6'), expect.stringContaining('Entrega 7'),
    ])
    expect(rows[0]!.text()).toContain('11:10')
    expect(rows[0]!.text()).toContain('API')
    expect(rows[0]!.attributes('href')).toBe('/sessions/s4')
    const more = wrapper.get('[data-test="start-delivered-more"]')
    expect(more.text()).toBe('Mais 3 entregas de hoje')
    expect(more.attributes('href')).toBe('/entregas')
    expect(wrapper.get('[data-test="start-delivered-section"]').text()).toContain('7 em 2 projetos')
  })

  it('usa o título do resumo quando existe', async () => {
    vi.stubGlobal('fetch', routes({ [DELIVERIES_URL]: () => jsonResponse(day([makeDelivery({ title: 'Original', summary_title: 'Título do resumo', finished_at: todayAt(9) })])) }))
    const { wrapper } = await mountStart()
    expect(wrapper.get('[data-test="start-delivered"]').text()).toContain('Título do resumo')
    expect(wrapper.find('[data-test="start-delivered-more"]').exists()).toBe(false)
  })

  it('sem entregas, diz que nada foi entregue', async () => {
    vi.stubGlobal('fetch', routes())
    const { wrapper } = await mountStart()
    expect(wrapper.get('[data-test="start-delivered-section"]').text()).toContain('Nada entregue hoje ainda.')
  })

  it('não mostra as entregas de outro dia que a tela Entregas deixou na loja', async () => {
    const store = useDeliveriesStore(pinia)
    store.day = day([makeDelivery({ title: 'Do dia errado' })], { date: '2020-01-01' })
    store.date = '2020-01-01'
    let release!: (r: Response) => void
    const pending = new Promise<Response>((resolve) => { release = resolve })
    vi.stubGlobal('fetch', routes({ [DELIVERIES_URL]: () => pending }))
    const { wrapper } = await mountStart()
    expect(wrapper.text()).not.toContain('Do dia errado')
    expect(wrapper.find('[data-test="start-delivered"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="start-delivered-section"] [role="status"]').exists()).toBe(true)
    release(jsonResponse(day([makeDelivery({ title: 'De hoje', finished_at: todayAt(9) })])))
    await flushPromises()
    expect(wrapper.text()).toContain('De hoje')
    expect(store.date).toBe(TODAY)
  })

  it('falha mostra o erro e deixa tentar de novo', async () => {
    let calls = 0
    const fetch = routes({
      [DELIVERIES_URL]: () => (++calls === 1 ? jsonResponse({ detail: 'Banco travado.' }, 500) : jsonResponse(day([makeDelivery({ title: 'Voltou', finished_at: todayAt(9) })]))),
    })
    vi.stubGlobal('fetch', fetch)
    const { wrapper } = await mountStart()
    expect(wrapper.get('[data-test="start-deliveries-error"]').text()).toContain('Banco travado.')
    expect(wrapper.find('[data-test="start-delivered"]').exists()).toBe(false)
    await wrapper.get('[data-test="start-deliveries-retry"]').trigger('click')
    await flushPromises()
    expect(fetch.mock.calls.filter((c) => c[0] === `/api/deliveries?date=${TODAY}`)).toHaveLength(2)
    expect(wrapper.find('[data-test="start-deliveries-error"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('Voltou')
  })
})
