import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import { createAppRouter } from '../../router'
import { jsonResponse, makeEvent, makeProject, makeSnapshot, routeFetch } from '../../test/factories'
import { useProjectsStore } from '../../stores/projects'
import type { WsEvent } from '../../types/events'

const fake = vi.hoisted(() => ({
  session: new Map<string, (e: unknown) => void>(),
  reconnect: new Set<() => void>(),
}))
vi.mock('../../api/socket', () => ({
  useEventSocket: () => ({
    onSession: (id: string, h: (e: unknown) => void) => { fake.session.set(id, h); return () => fake.session.delete(id) },
    onReconnect: (h: () => void) => { fake.reconnect.add(h); return () => fake.reconnect.delete(h) },
  }),
}))

import SessionView from '../SessionView.vue'

enableAutoUnmount(afterEach)
let pinia: Pinia

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  fake.session.clear()
  fake.reconnect.clear()
  const projects = useProjectsStore(pinia)
  projects.projects = [makeProject({ id: 1, name: 'loja-online' })]
  projects.loaded = true
})
afterEach(() => vi.unstubAllGlobals())

const text = (id: string, t: string) => ({ type: 'text', id, text: t, streaming: false, parent_tool_use_id: null })

async function mountView() {
  const router = createAppRouter(createMemoryHistory())
  await router.push('/sessions/s1')
  const w = mount(SessionView, { props: { id: 's1' }, global: { plugins: [pinia, router] } })
  await flushPromises()
  return w
}

describe('tela da sessão', () => {
  it('carrega o retrato e mostra cabeçalho, itens e campo', async () => {
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/sessions/s1': () => jsonResponse(makeSnapshot({ title: 'Cupom expirado', state: 'idle', seq: 2, items: [text('a', 'Olá do retrato') as never] })),
    }))
    const w = await mountView()
    expect(w.find('h2').text()).toBe('Cupom expirado')
    expect(w.text()).toContain('loja-online')
    expect(w.text()).toContain('Parada')
    expect(w.text()).toContain('Olá do retrato')
    expect(w.find('textarea').exists()).toBe(true)
    expect(w.find('[data-test="interrupt"]').exists()).toBe(false)
  })

  it('aplica eventos do socket, mostra "Interromper" rodando e cartão de permissão', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/sessions/s1': () => jsonResponse(makeSnapshot({ seq: 1 })) }))
    const w = await mountView()
    const emit = (e: WsEvent) => fake.session.get('s1')!(e)
    emit(makeEvent('item.upsert', text('b', 'Novo texto'), 2))
    emit(makeEvent('session.state', { state: 'running', error: null }, 3))
    emit(makeEvent('prompt.request', { prompt_id: 'p1', tool_name: 'Bash', input: { command: 'ls' }, can_always: false }, 4))
    emit(makeEvent('turn.result', { subtype: 'success', is_error: false, duration_ms: 1500, total_cost_usd: 0.0123 }, 5))
    await flushPromises()
    expect(w.text()).toContain('Novo texto')
    expect(w.find('[data-test="interrupt"]').exists()).toBe(true)
    expect(w.find('[data-test="permission-card"]').exists()).toBe(true)
    expect(w.find('[data-test="turn-footer"]').text()).toContain('1,5 s')
    emit(makeEvent('prompt.resolved', { prompt_id: 'p1', decision: 'allow_once' }, 6))
    await flushPromises()
    expect(w.find('[data-test="permission-card"]').exists()).toBe(false)
  })

  it('mostra o erro da sessão acima do campo', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/sessions/s1': () => jsonResponse(makeSnapshot({ state: 'error', error: 'O processo caiu.' })) }))
    const w = await mountView()
    expect(w.find('[data-test="session-error"]').text()).toContain('O processo caiu.')
  })

  it('recarrega o retrato ao reconectar', async () => {
    let calls = 0
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/sessions/s1': () => {
        calls++
        return jsonResponse(makeSnapshot({ seq: calls, items: calls > 1 ? [text('z', 'Depois da queda') as never] : [] }))
      },
    }))
    const w = await mountView()
    fake.reconnect.forEach((h) => h())
    await flushPromises()
    expect(calls).toBe(2)
    expect(w.text()).toContain('Depois da queda')
  })

  it('mostra o erro ao carregar', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/sessions/s1': () => jsonResponse({ detail: 'Sessão não encontrada.' }, 404) }))
    const w = await mountView()
    expect(w.find('[role="alert"]').text()).toContain('Sessão não encontrada.')
  })

  it('cancela as assinaturas do socket ao trocar de sessão e no unmount', async () => {
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/sessions/s1': () => jsonResponse(makeSnapshot()),
      'GET /api/sessions/s2': () => jsonResponse(makeSnapshot({ session_id: 's2' })),
    }))
    const w = await mountView()
    expect([...fake.session.keys()]).toEqual(['s1'])
    expect(fake.reconnect.size).toBe(1)
    await w.setProps({ id: 's2' })
    await flushPromises()
    expect([...fake.session.keys()]).toEqual(['s2'])
    expect(fake.reconnect.size).toBe(1)
    w.unmount()
    expect(fake.session.size).toBe(0)
    expect(fake.reconnect.size).toBe(0)
  })
})
