import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { mount, flushPromises, enableAutoUnmount } from '@vue/test-utils'
import WorkContinuation from '../WorkContinuation.vue'
import type { WorkAttention } from '../../../types/work'
import { jsonResponse } from '../../../test/factories'

enableAutoUnmount(afterEach)
beforeEach(() => sessionStorage.clear())
afterEach(() => vi.unstubAllGlobals())
const attention: WorkAttention = { work_item_id: 1, title: 'Coletar Sentry', attempt_id: 11, session_id: 'sentry-exact', kind: 'continuation' as const, can_continue: true, queue_reason: null }
it('abre vazio, explicita destino e só envia a orientação digitada à sessão exata', async () => {
  const fetch = vi.fn(async (_url: string, _init?: RequestInit) => jsonResponse({ state: 'running', external_activity: false, send_started: true }, 202)); vi.stubGlobal('fetch', fetch)
  const wrapper = mount(WorkContinuation, { props: { attention } })
  expect(wrapper.find('textarea').exists()).toBe(false)
  await wrapper.get('button').trigger('click')
  expect(wrapper.get('textarea').element.value).toBe('')
  expect(wrapper.text()).toContain('Coletar Sentry')
  expect(wrapper.text()).toContain('tentativa #11')
  expect(fetch).not.toHaveBeenCalled()
  await wrapper.get('textarea').setValue('Use o ambiente prd para esta coleta')
  await wrapper.get('form').trigger('submit'); await flushPromises()
  expect(fetch.mock.calls[0]?.[0]).toBe('/api/sessions/sentry-exact/messages')
  expect(JSON.parse(fetch.mock.calls[0]?.[1]?.body as string)).toEqual({ text: 'Use o ambiente prd para esta coleta' })
  expect(wrapper.text()).toContain('Orientação enviada')
  expect(wrapper.emitted('sent')).toHaveLength(1)
})
it('preserva rascunho em conflito e ao trocar de tentativa, sem repetir envio', async () => {
  const fetch = vi.fn(async () => jsonResponse({ detail: 'Execução mudou' }, 409)); vi.stubGlobal('fetch', fetch)
  const wrapper = mount(WorkContinuation, { props: { attention } })
  await wrapper.get('button').trigger('click'); await wrapper.get('textarea').setValue('Minha orientação')
  await wrapper.get('form').trigger('submit'); await flushPromises()
  expect(wrapper.get('textarea').element.value).toBe('Minha orientação')
  expect(wrapper.get('[role="alert"]').text()).toContain('Execução mudou')
  await wrapper.setProps({ attention: { ...attention, attempt_id: 12, session_id: 'other' } })
  await wrapper.get('button').trigger('click')
  expect(wrapper.get('textarea').element.value).toBe('')
  await wrapper.setProps({ attention }); await wrapper.get('button').trigger('click')
  expect(wrapper.get('textarea').element.value).toBe('Minha orientação')
  expect(fetch).toHaveBeenCalledTimes(1)
})
it.each(['decision', 'permission', 'waiting', 'running', 'uncertain', 'paused', 'queued', 'inactive'])('não oferece continuação em %s', (kind) => {
  const wrapper = mount(WorkContinuation, { props: { attention: { ...attention, kind, can_continue: false } as typeof attention, initiallyOpen: true } })
  expect(wrapper.find('button').exists()).toBe(false)
  expect(wrapper.find('form').exists()).toBe(false)
})
it('não transfere confirmação de resposta HTTP antiga para outra sessão', async () => {
  let resolve!: (response: Response) => void
  vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(done => resolve = done)))
  const wrapper = mount(WorkContinuation, { props: { attention } })
  await wrapper.get('button').trigger('click'); await wrapper.get('textarea').setValue('Rascunho antigo'); await wrapper.get('form').trigger('submit')
  await wrapper.setProps({ attention: { ...attention, attempt_id: 12, session_id: 'other' } })
  resolve(jsonResponse({}, 202)); await flushPromises()
  expect(wrapper.text()).not.toContain('Orientação enviada')
  await wrapper.get('button').trigger('click'); expect(wrapper.get('textarea').element.value).toBe('')
})

it('mantém rascunho visível mas impede envio quando deixa de ser elegível', async () => {
  const fetch = vi.fn(); vi.stubGlobal('fetch', fetch)
  const wrapper = mount(WorkContinuation, { props: { attention } })
  await wrapper.get('button').trigger('click'); await wrapper.get('textarea').setValue('Não perder este contexto')
  await wrapper.setProps({ attention: { ...attention, kind: 'uncertain', can_continue: false } as typeof attention })
  expect(wrapper.get('textarea').element.value).toBe('Não perder este contexto')
  expect(wrapper.get('button[type="submit"]').attributes('disabled')).toBeDefined()
  await wrapper.get('form').trigger('submit'); await flushPromises()
  expect(fetch).not.toHaveBeenCalled()
})

it.each([
  { state: 'error', external_activity: false, send_started: true },
  { state: 'idle', external_activity: false, send_started: false },
])('202 sem envio comprovado mantém rascunho e não confirma sucesso: %j', async (result) => {
  const fetch = vi.fn(async () => jsonResponse(result, 202)); vi.stubGlobal('fetch', fetch)
  const wrapper = mount(WorkContinuation, { props: { attention } })
  await wrapper.get('button').trigger('click'); await wrapper.get('textarea').setValue('Orientação que não deve sumir')
  await wrapper.get('form').trigger('submit'); await flushPromises()
  expect(wrapper.text()).not.toContain('Orientação enviada')
  expect(wrapper.get('textarea').element.value).toBe('Orientação que não deve sumir')
  expect(wrapper.find('[role="alert"]').exists()).toBe(true)
  expect(wrapper.emitted('sent')).toBeUndefined()
  expect(wrapper.emitted('stale')).toHaveLength(1)
  expect(fetch).toHaveBeenCalledTimes(1)
})

it('resposta de instância desmontada não apaga novo rascunho na mesma tentativa nem emite eventos', async () => {
  let resolve!: (response: Response) => void
  const fetch = vi.fn(() => new Promise<Response>(done => resolve = done)); vi.stubGlobal('fetch', fetch)
  const first = mount(WorkContinuation, { props: { attention, initiallyOpen: true } })
  await first.get('textarea').setValue('Orientação A')
  await first.get('form').trigger('submit')
  first.unmount()
  const second = mount(WorkContinuation, { props: { attention, initiallyOpen: true } })
  await second.get('textarea').setValue('Rascunho B')
  resolve(jsonResponse({ state: 'running', external_activity: false, send_started: true }, 202)); await flushPromises()
  expect(first.emitted('sent')).toBeUndefined()
  expect(first.emitted('stale')).toBeUndefined()
  expect(second.get('textarea').element.value).toBe('Rascunho B')
  second.unmount()
  const third = mount(WorkContinuation, { props: { attention, initiallyOpen: true } })
  expect(third.get('textarea').element.value).toBe('Rascunho B')
  expect(fetch).toHaveBeenCalledTimes(1)
})

it('callback de destino anterior preserva rascunho alterado por outra instância', async () => {
  let resolve!: (response: Response) => void
  vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(done => resolve = done)))
  const first = mount(WorkContinuation, { props: { attention, initiallyOpen: true } })
  await first.get('textarea').setValue('Orientação A'); await first.get('form').trigger('submit')
  await first.setProps({ attention: { ...attention, attempt_id: 12, session_id: 'other' } })
  await first.get('textarea').setValue('Rascunho outro destino')
  const second = mount(WorkContinuation, { props: { attention, initiallyOpen: true } })
  await second.get('textarea').setValue('Rascunho B')
  resolve(jsonResponse({ state: 'running', external_activity: false, send_started: true }, 202)); await flushPromises()
  expect(first.emitted('sent')).toBeUndefined()
  expect(first.get('textarea').element.value).toBe('Rascunho outro destino')
  second.unmount()
  const third = mount(WorkContinuation, { props: { attention, initiallyOpen: true } })
  expect(third.get('textarea').element.value).toBe('Rascunho B')
})
