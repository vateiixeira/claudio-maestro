import { beforeEach, afterEach, expect, it, vi } from 'vitest'
import { mount, flushPromises, enableAutoUnmount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import { createAppRouter } from '../../router'
import CtoView from '../CtoView.vue'
import { useProjectsStore } from '../../stores/projects'
import { makeProject, routeFetch, jsonResponse } from '../../test/factories'
enableAutoUnmount(afterEach)
beforeEach(() => { setActivePinia(createPinia()); useProjectsStore().projects = [makeProject({ id: 1 }), makeProject({ id: 2 })] })
afterEach(() => vi.unstubAllGlobals())
it('trocar projeto abre o CTO correto e não troca o diretório de uma sessão viva', async () => {
  const fetch = routeFetch({
    'POST /api/projects/1/cto': () => jsonResponse({ session_id: 'cto-one', project_id: 1 }),
    'POST /api/projects/2/cto': () => jsonResponse({ session_id: 'cto-two', project_id: 2 }),
    'GET /api/projects/1/work-mode': () => jsonResponse({ enabled: true, paused: false }),
    'GET /api/projects/2/work-mode': () => jsonResponse({ enabled: false, paused: false }),
    'GET /api/work/runtime': () => jsonResponse({ dispatcher_enabled: false }),
  }); vi.stubGlobal('fetch', fetch)
  const router = createAppRouter(createMemoryHistory()); await router.push('/cto?projeto=1')
  const wrapper = mount(CtoView, { global: { plugins: [router], stubs: { ConversationView: { props: ['id'], template: '<div data-test="cto-conversation">{{ id }}</div>' } } } })
  await flushPromises(); expect(wrapper.get('[data-test="cto-conversation"]').text()).toBe('cto-one')
  await wrapper.get('select').setValue('2'); await flushPromises()
  expect(wrapper.get('[data-test="cto-conversation"]').text()).toBe('cto-two')
  expect(fetch.mock.calls.some(call => call[1]?.method === 'PATCH')).toBe(false)
})

it('resposta atrasada de pausa não altera o modo do projeto recém-aberto', async () => {
  let pause!: (value: Response) => void
  vi.stubGlobal('fetch', routeFetch({
    'POST /api/projects/1/cto': () => jsonResponse({ session_id: 'cto-one' }),
    'POST /api/projects/2/cto': () => jsonResponse({ session_id: 'cto-two' }),
    'GET /api/projects/1/work-mode': () => jsonResponse({ enabled: true, paused: false }),
    'GET /api/projects/2/work-mode': () => jsonResponse({ enabled: true, paused: false }),
    'GET /api/work/runtime': () => jsonResponse({ dispatcher_enabled: true }),
    'POST /api/projects/1/work-mode': () => new Promise<Response>(resolve => { pause = resolve }),
  }))
  const router = createAppRouter(createMemoryHistory()); await router.push('/cto?projeto=1')
  const wrapper = mount(CtoView, { global: { plugins: [router], stubs: { ConversationView: true } } })
  await flushPromises()
  await wrapper.findAll('button').find(b => b.text() === 'Pausar trabalho')!.trigger('click')
  await wrapper.get('select').setValue('2'); await flushPromises()
  pause(jsonResponse({ enabled: true, paused: true })); await flushPromises()
  expect(wrapper.text()).toContain('Coordenação ativa')
  expect(wrapper.text()).not.toContain('Trabalhadores pausados')
})

it('limpar projeto enquanto abre uma conversa pendente volta à escolha de projeto', async () => {
  let release!: (value: Response) => void
  vi.stubGlobal('fetch', routeFetch({
    'POST /api/projects/1/cto': () => new Promise<Response>(resolve => { release = resolve }),
    'GET /api/projects/1/work-mode': () => jsonResponse({ enabled: true, paused: false }),
    'GET /api/work/runtime': () => jsonResponse({ dispatcher_enabled: false }),
  }))
  const router = createAppRouter(createMemoryHistory()); await router.push('/cto?projeto=1')
  const wrapper = mount(CtoView, { global: { plugins: [router], stubs: { ConversationView: true } } })
  await flushPromises(); expect(wrapper.text()).toContain('Abrindo conversa do CTO')
  await wrapper.get('select').setValue(''); await flushPromises()
  expect(wrapper.text()).toContain('Escolha onde o trabalho acontece')
  expect(wrapper.text()).not.toContain('Abrindo conversa do CTO')
  release(jsonResponse({ session_id: 'old-cto' })); await flushPromises()
  expect(wrapper.text()).toContain('Escolha onde o trabalho acontece')
})
