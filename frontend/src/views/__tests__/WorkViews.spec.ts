import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises, enableAutoUnmount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import { createAppRouter } from '../../router'
import TasksView from '../TasksView.vue'
import StartView from '../StartView.vue'
import DecisionRequest from '../../components/work/DecisionRequest.vue'
import { jsonResponse, makeProject, routeFetch } from '../../test/factories'
import { useProjectsStore } from '../../stores/projects'
enableAutoUnmount(afterEach)
beforeEach(() => { setActivePinia(createPinia()); useProjectsStore().projects = [makeProject({ id: 2, name: 'Loja' })] })
afterEach(() => vi.unstubAllGlobals())
async function routerAt(path: string) { const router = createAppRouter(createMemoryHistory()); await router.push(path); return router }
describe('produto centrado em tarefas', () => {
  it('raiz abre início e mantém os links antigos', async () => {
    const router = await routerAt('/')
    expect(router.currentRoute.value.path).toBe('/inicio')
    for (const path of ['/sessions/abc', '/agentes/1', '/inbox', '/dashboard']) expect(router.resolve(path).matched.length).toBe(1)
  })
  it('filtros na URL e próxima página usam o total do servidor', async () => {
    const fetch = routeFetch({
      'GET /api/work-items?project_id=2&status=active&source=sentry&limit=30&offset=0': () => jsonResponse({ items: [], total: 70, limit: 30, offset: 0 }),
      'GET /api/work-items?project_id=2&status=active&source=sentry&limit=30&offset=30': () => jsonResponse({ items: [], total: 70, limit: 30, offset: 30 }),
    })
    vi.stubGlobal('fetch', fetch)
    const router = await routerAt('/tarefas?project=2&status=active&source=sentry')
    const wrapper = mount(TasksView, { global: { plugins: [router] } })
    await flushPromises()
    expect(wrapper.get('[data-test="work-total"]').text()).toContain('70')
    await wrapper.get('[data-test="work-next"]').trigger('click'); await flushPromises()
    expect(router.currentRoute.value.query.page).toBe('2')
  })
  it('exige projeto explícito para entregar um objetivo ao CTO', async () => {
    vi.stubGlobal('fetch', routeFetch({
      ...Object.fromEntries(['active', 'waiting', 'review', 'blocked', 'ready', 'done'].map(status => [`GET /api/work-items?status=${status}&limit=${status === 'done' ? 5 : 8}&offset=0`, () => jsonResponse({ items: [], total: 0, limit: 8, offset: 0 })])),
      'GET /api/work/decisions?pending_only=true': () => jsonResponse({ items: [] }),
      'GET /api/work/notifications?latest=true': () => jsonResponse({ items: [], after: 0 }),
      'GET /api/work/runtime': () => jsonResponse({ dispatcher_enabled: false }),
    }))
    const router = await routerAt('/inicio')
    const wrapper = mount(StartView, { global: { plugins: [router] } })
    await flushPromises()
    await wrapper.get('textarea').setValue('Investigar falha de pagamento')
    expect(wrapper.get('[data-test="goal-submit"]').attributes('disabled')).toBeDefined()
    await wrapper.get('select').setValue('2')
    expect(wrapper.get('[data-test="goal-submit"]').attributes('disabled')).toBeUndefined()
  })
  it('resposta humana inclui revisão e recibo, impede envio duplo e mostra 409', async () => {
    let done!: (value: Response) => void
    const fetch = vi.fn((_url: string, _init?: RequestInit) => new Promise<Response>(resolve => { done = resolve }))
    vi.stubGlobal('fetch', fetch)
    const wrapper = mount(DecisionRequest, { props: { decision: { id: 3, revision: 7, status: 'pending', work_item_id: 1, attempt_id: 4, request: { question: 'Publicar?', action: 'deploy' } } } })
    await wrapper.get('textarea').setValue('Somente homologação')
    await wrapper.get('form').trigger('submit'); await wrapper.get('form').trigger('submit')
    expect(fetch).toHaveBeenCalledTimes(1)
    const body = JSON.parse(String(fetch.mock.calls[0]?.[1]?.body))
    expect(body).toMatchObject({ expected_revision: 7, answer: 'Somente homologação' }); expect(body.receipt).toBeTruthy()
    done(jsonResponse({ detail: 'A decisão mudou.' }, 409)); await flushPromises()
    expect(wrapper.text()).toContain('A decisão mudou')
  })
})

it('entrega objetivo uma vez à conversa persistente do projeto escolhido', async () => {
  const fetch = routeFetch({
    ...Object.fromEntries(['active', 'waiting', 'review', 'blocked', 'ready', 'done'].map(status => [`GET /api/work-items?status=${status}&limit=${status === 'done' ? 5 : 8}&offset=0`, () => jsonResponse({ items: [], total: 0, limit: 8, offset: 0 })])),
    'GET /api/work/decisions?pending_only=true': () => jsonResponse({ items: [] }),
    'GET /api/work/notifications?latest=true': () => jsonResponse({ items: [], after: 0 }),
    'GET /api/work/runtime': () => jsonResponse({ dispatcher_enabled: false }),
    'POST /api/projects/2/cto': () => jsonResponse({ session_id: 'cto-two', project_id: 2 }),
    'POST /api/sessions/cto-two/messages': () => jsonResponse({ state: 'running' }),
  }); vi.stubGlobal('fetch', fetch)
  const router = await routerAt('/inicio')
  const wrapper = mount(StartView, { global: { plugins: [router] } })
  await flushPromises(); await wrapper.get('select').setValue('2')
  await wrapper.get('textarea').setValue('Investigar sem publicar')
  await wrapper.get('form').trigger('submit'); await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(router.currentRoute.value.fullPath).toBe('/agentes/2')
  const messages = fetch.mock.calls.filter(call => call[0] === '/api/sessions/cto-two/messages')
  expect(messages).toHaveLength(1)
  expect(JSON.parse(String(messages[0]?.[1]?.body))).toEqual({ text: 'Investigar sem publicar' })
})

it('mantém os rascunhos de objetivo separados por projeto', async () => {
  const { goalDrafts } = await import('../../workGoal')
  for (const key of Object.keys(goalDrafts)) delete goalDrafts[key]
  useProjectsStore().projects.push(makeProject({ id: 3, name: 'API' }))
  vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ items: [], total: 0, limit: 100, offset: 0, dispatcher_enabled: false })))
  const router = await routerAt('/inicio')
  const wrapper = mount(StartView, { global: { plugins: [router] } })
  await flushPromises()
  await wrapper.get('select').setValue('2'); await wrapper.get('textarea').setValue('Objetivo da loja')
  await wrapper.get('select').setValue('3'); expect((wrapper.get('textarea').element as HTMLTextAreaElement).value).toBe('')
  await wrapper.get('textarea').setValue('Objetivo da API')
  await wrapper.get('select').setValue('2'); expect((wrapper.get('textarea').element as HTMLTextAreaElement).value).toBe('Objetivo da loja')
})

it('trocar pedido de decisão com mesma revisão limpa resposta e recibo anteriores', async () => {
  const fetch = vi.fn(async () => jsonResponse({})); vi.stubGlobal('fetch', fetch)
  const decision = { id: 1, revision: 1, status: 'pending', work_item_id: 1, attempt_id: 1, request: { question: 'Primeira decisão', action: 'ação 1' } }
  const wrapper = mount(DecisionRequest, { props: { decision } })
  await wrapper.get('textarea').setValue('Autorizar ação 1')
  await wrapper.setProps({ decision: { ...decision, id: 2, request: { question: 'Outra decisão', action: 'ação 2' } } })
  expect((wrapper.get('textarea').element as HTMLTextAreaElement).value).toBe('')
  expect(wrapper.get('button[type="submit"]').attributes('disabled')).toBeDefined()
})

it('detalhe preserva a resposta humana depois que uma nova tentativa consome a decisão', async () => {
  const { default: TaskView } = await import('../TaskView.vue')
  vi.stubGlobal('fetch', routeFetch({
    'GET /api/work/runtime': () => jsonResponse({ dispatcher_enabled: true }),
    'GET /api/work-items/7': () => jsonResponse({ item: { id: 7, project_id: 2, title: 'Investigar', status: 'done', revision: 4, updated_at: 100 }, dossier: {}, attempts: [], events: [], dependencies: [], decisions: [{ id: 3, status: 'resumed', revision: 2, work_item_id: 7, attempt_id: 11, request: { question: 'Preservar contrato?', action: 'Preservar' }, answer: { answer: 'Manter contrato atual' } }] }),
  }))
  const router = await routerAt('/tarefas/7')
  const wrapper = mount(TaskView, { props: { id: '7' }, global: { plugins: [router] } })
  await flushPromises()
  expect(wrapper.text()).toContain('Manter contrato atual')
  expect(wrapper.text()).toContain('Continuidade iniciada em nova tentativa')
  expect(wrapper.text()).not.toContain('Sua decisão')
})

it('decisão expirada sem resposta não oferece formulário', () => {
  const wrapper = mount(DecisionRequest, { props: { decision: { id: 4, revision: 2, status: 'expired', work_item_id: 1, attempt_id: 2, request: { question: 'Publicar?', action: 'deploy' } } } })
  expect(wrapper.text()).toContain('Decisão expirada')
  expect(wrapper.find('form').exists()).toBe(false)
})
it('aceitação remove o formulário enquanto a atualização do pedido ainda está pendente', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ status: 'answered' }, 202)))
  const wrapper = mount(DecisionRequest, { props: { decision: { id: 4, revision: 1, status: 'pending', work_item_id: 1, attempt_id: 2, request: { question: 'Publicar?', action: 'deploy' } } } })
  await wrapper.get('textarea').setValue('Não')
  await wrapper.get('form').trigger('submit'); await flushPromises()
  expect(wrapper.text()).toContain('Resposta registrada')
  expect(wrapper.find('form').exists()).toBe(false)
})
it('início consulta estados antes da paginação e conserva trabalho antigo atrás de 100 metadados', async () => {
  const active = { id: 1, project_id: 2, title: 'Execução antiga ainda ativa', status: 'active', source: 'manual', updated_at: 20 }
  const done = { ...active, id: 2, title: 'Entrega validada', status: 'done', updated_at: 10 }
  const fetch = vi.fn(async (raw: string) => {
    const url = new URL(raw, 'http://localhost')
    if (url.pathname === '/api/work-items') {
      const status = url.searchParams.get('status')
      const items = status === 'active' ? [active] : status === 'done' ? [done] : status ? [] : Array.from({ length: 100 }, (_, id) => ({ ...active, id: id + 100, status: 'backlog' }))
      return jsonResponse({ items, total: items.length, limit: 8, offset: 0 })
    }
    return jsonResponse({ items: [], after: 0, dispatcher_enabled: true })
  }); vi.stubGlobal('fetch', fetch)
  const router = await routerAt('/inicio')
  const wrapper = mount(StartView, { global: { plugins: [router] } })
  await flushPromises()
  expect(wrapper.text()).toContain(active.title)
  expect(wrapper.text()).toContain(done.title)
  expect(fetch.mock.calls.filter(([url]) => url.startsWith('/api/work-items')).every(([url]) => new URL(url, 'http://localhost').searchParams.has('status'))).toBe(true)
})

it('CTO lê a janela recente após 100 avisos e confirma o maior recibo mostrado', async () => {
  const { default: CoordinatorWork } = await import('../../components/work/CoordinatorWork.vue')
  const fetch = vi.fn(async (raw: string, _init?: RequestInit) => {
    if (raw.includes('/work-feed')) return jsonResponse({ items: new URL(raw, 'http://localhost').searchParams.get('latest') === 'true' ? [{ id: 151, work_item_id: 7, summary: 'Aviso recente 151', dispatch_state: 'sent' }] : [{ id: 1, summary: 'Aviso antigo' }], after: raw.includes('latest=true') ? 151 : 1 })
    return jsonResponse({ items: [], total: 0 })
  }); vi.stubGlobal('fetch', fetch)
  const router = await routerAt('/cto?projeto=2')
  const wrapper = mount(CoordinatorWork, { props: { projectId: 2 }, global: { plugins: [router] } })
  await flushPromises()
  expect(wrapper.text()).toContain('Aviso recente 151')
  const seen = fetch.mock.calls.find(([url]) => url.endsWith('/work-feed/seen'))
  expect(seen).toBeTruthy()
  expect(JSON.parse(String(seen?.[1]?.body))).toEqual({ through: 151 })
})
