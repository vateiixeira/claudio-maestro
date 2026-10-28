import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises, enableAutoUnmount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import { createAppRouter } from '../../router'
import DecisionRequest from '../../components/work/DecisionRequest.vue'
import { jsonResponse, makeProject } from '../../test/factories'
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

it('trocar pedido de decisão com mesma revisão limpa resposta e recibo anteriores', async () => {
  const fetch = vi.fn(async () => jsonResponse({})); vi.stubGlobal('fetch', fetch)
  const decision = { id: 1, revision: 1, status: 'pending', work_item_id: 1, attempt_id: 1, request: { question: 'Primeira decisão', action: 'ação 1' } }
  const wrapper = mount(DecisionRequest, { props: { decision } })
  await wrapper.get('textarea').setValue('Autorizar ação 1')
  await wrapper.setProps({ decision: { ...decision, id: 2, request: { question: 'Outra decisão', action: 'ação 2' } } })
  expect((wrapper.get('textarea').element as HTMLTextAreaElement).value).toBe('')
  expect(wrapper.get('button[type="submit"]').attributes('disabled')).toBeDefined()
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
