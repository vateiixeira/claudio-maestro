import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import StartView from '../StartView.vue'
import { createAppRouter } from '../../router'
import { goalDrafts } from '../../goalDrafts'
import { useOrgStore } from '../../stores/org'
import { useProjectsStore } from '../../stores/projects'
import { useSessionsStore } from '../../stores/sessions'
import { useTasksStore } from '../../stores/tasks'
import { jsonResponse, makeAgent, makeDecision, makeProject, makeSession, makeTask, routeFetch } from '../../test/factories'

enableAutoUnmount(afterEach)
let pinia: Pinia

const ACTIVE_URL = 'GET /api/tasks?status=in_progress&status=in_review&status=blocked&limit=8&order=recent'
const DONE_URL = 'GET /api/tasks?status=done&limit=5&order=recent'

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

function routes(extra: Record<string, (init?: RequestInit) => Response> = {}) {
  return routeFetch({
    [ACTIVE_URL]: () => jsonResponse([]),
    [DONE_URL]: () => jsonResponse([]),
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

describe('objetivo', () => {
  it('entrega ao topo do projeto e leva ao painel dele', async () => {
    const fetch = routes({
      'POST /api/agents/11/main': () => jsonResponse({ session_id: 'main-11' }),
      'POST /api/sessions/main-11/messages': () => jsonResponse({ state: 'running' }),
    })
    vi.stubGlobal('fetch', fetch)
    const { wrapper, router } = await mountStart()
    await wrapper.get('select').setValue('2')
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
    await wrapper.get('select').setValue('3')
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
    await wrapper.get('select').setValue('2')
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
    await wrapper.get('select').setValue('2')
    await wrapper.get('textarea').setValue('Objetivo da loja')
    await wrapper.get('select').setValue('3')
    expect((wrapper.get('textarea').element as HTMLTextAreaElement).value).toBe('')
    await wrapper.get('textarea').setValue('Objetivo da API')
    await wrapper.get('select').setValue('2')
    expect((wrapper.get('textarea').element as HTMLTextAreaElement).value).toBe('Objetivo da loja')
  })

  it('não tem mais o aviso do despacho desligado', async () => {
    vi.stubGlobal('fetch', routes())
    const { wrapper } = await mountStart()
    expect(wrapper.text()).not.toContain('despacho')
  })
})

describe('o que está acontecendo', () => {
  it('lista decisões e tarefas em andamento', async () => {
    useOrgStore(pinia).decisionsPending = [makeDecision({ id: 5, question: 'Posso publicar?' })]
    useSessionsStore(pinia).setForProject(2, [
      makeSession({ session_id: 'w1', project_id: 2, title: 'Pede permissão', display_state: 'waiting', state: 'awaiting_decision', pending_kind: 'tool' }),
    ])
    vi.stubGlobal('fetch', routes({
      [ACTIVE_URL]: () => jsonResponse([
        makeTask({ id: 2, project_id: 3, title: 'Recente', status: 'blocked', updated_at: 30 }),
        makeTask({ id: 3, project_id: 2, title: 'Meio', status: 'in_review', updated_at: 20 }),
        makeTask({ id: 1, project_id: 2, title: 'Antiga', status: 'in_progress', updated_at: 10 }),
      ]),
      [DONE_URL]: () => jsonResponse([makeTask({ id: 4, title: 'Entregue', status: 'done', updated_at: 5 })]),
    }))
    const { wrapper } = await mountStart()
    const need = wrapper.get('[aria-labelledby="need-you-title"]')
    expect(need.get('[data-test="decision-card"]').text()).toContain('Posso publicar?')
    expect(need.text()).toContain('Pede permissão')
    const active = wrapper.get('[aria-labelledby="active-title"]')
    expect(active.findAll('[data-test="start-task"]').map((r) => r.text())).toEqual([
      expect.stringContaining('Recente'), expect.stringContaining('Meio'), expect.stringContaining('Antiga'),
    ])
    expect(active.findAll('[data-test="start-task"]')[0]!.attributes('href')).toBe('/tarefas/2')
    expect(active.text()).toContain('API')
    expect(active.text()).toContain('Bloqueada')
    const recent = wrapper.get('[aria-labelledby="recent-title"]')
    expect(recent.findAll('[data-test="start-task"]')).toHaveLength(1)
    expect(recent.text()).toContain('Entregue')
  })

  it('pede ao servidor só as mais recentes: 8 em andamento e 5 concluídas', async () => {
    const fetch = routes()
    vi.stubGlobal('fetch', fetch)
    await mountStart()
    const urls = fetch.mock.calls.map((c) => c[0])
    expect(urls).toContain('/api/tasks?status=in_progress&status=in_review&status=blocked&limit=8&order=recent')
    expect(urls).toContain('/api/tasks?status=done&limit=5&order=recent')
  })

  it('sem nada, mostra os estados vazios e nenhuma seção "Precisam de você"', async () => {
    vi.stubGlobal('fetch', routes())
    const { wrapper } = await mountStart()
    expect(wrapper.find('[aria-labelledby="need-you-title"]').exists()).toBe(false)
    expect(wrapper.get('[aria-labelledby="active-title"]').text()).toContain('O próximo passo começa com um objetivo')
  })

  it('falha ao carregar as tarefas avisa e deixa tentar de novo', async () => {
    let calls = 0
    vi.stubGlobal('fetch', routes({
      [ACTIVE_URL]: () => (++calls === 1 ? jsonResponse({ detail: 'Banco travado.' }, 500) : jsonResponse([makeTask({ id: 1, title: 'Voltou', status: 'in_progress' })])),
    }))
    const { wrapper } = await mountStart()
    expect(wrapper.get('[data-test="start-error"]').text()).toContain('Banco travado.')
    await wrapper.get('[data-test="start-retry"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-test="start-error"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('Voltou')
  })

  it('recarrega quando um evento de tarefa invalida as listas', async () => {
    let tasks = [makeTask({ id: 1, title: 'Primeira', status: 'in_progress' })]
    vi.stubGlobal('fetch', routes({ [ACTIVE_URL]: () => jsonResponse(tasks) }))
    const { wrapper } = await mountStart()
    expect(wrapper.text()).toContain('Primeira')
    tasks = [...tasks, makeTask({ id: 2, title: 'Segunda', status: 'in_progress' })]
    useTasksStore(pinia).applyEvent({ id: 2, project_id: 2, status: 'in_progress' })
    await flushPromises()
    expect(wrapper.text()).toContain('Segunda')
  })
})
