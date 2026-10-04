// frontend/src/components/details/__tests__/ClosureBlock.spec.ts
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import ClosureBlock from '../ClosureBlock.vue'
import { jsonResponse, makeSession, routeFetch } from '../../../test/factories'
import { useSessionsStore } from '../../../stores/sessions'
import type { ClosureVerdict, SessionClosure } from '../../../types/api'

enableAutoUnmount(afterEach)

const MIDDAY = new Date(2026, 9, 3, 12, 0, 0)
const NOW = Math.floor(MIDDAY.getTime() / 1000)

let pinia: Pinia
let resolves: unknown[]
let patches: unknown[]

function closure(overrides: Partial<SessionClosure> = {}): SessionClosure {
  return { session_id: 's1', verdict: 'user_action', user_actions: ['Reiniciar os serviços'], missing: ['Tarefa 5 sem commit'], evidence: 'Falta reiniciar', checked_at: NOW - 120, error: null, error_at: null, ...overrides }
}

function setup(verdict: ClosureVerdict | null, body: SessionClosure | null, display_state: 'waiting' | 'finished' = 'waiting') {
  vi.stubGlobal('fetch', routeFetch({
    'GET /api/sessions/s1/closure': () => jsonResponse(body),
    'POST /api/sessions/s1/closure/resolve': async (init?: RequestInit) => {
      resolves.push(JSON.parse(String(init?.body)))
      return jsonResponse(closure({ verdict: 'incomplete', user_actions: [] }))
    },
    'PATCH /api/sessions/s1': async (init?: RequestInit) => {
      patches.push(JSON.parse(String(init?.body)))
      return jsonResponse(makeSession({ finished: true, display_state: 'finished' }))
    },
  }))
  useSessionsStore().setForProject(1, [makeSession({ closure_verdict: verdict, display_state })])
}

async function mountBlock() {
  const w = mount(ClosureBlock, { props: { sessionId: 's1' }, global: { plugins: [pinia] } })
  await flushPromises()
  return w
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(MIDDAY)
  pinia = createPinia()
  setActivePinia(pinia)
  resolves = []
  patches = []
})
afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('bloco Fechamento', () => {
  it('mostra o selo, o que falta fazer com Já fiz e o que falta implementar sem botão', async () => {
    setup('user_action', closure())
    const w = await mountBlock()
    expect(w.get('[data-test="closure-badge"]').text()).toBe('Falta ação sua')
    const action = w.get('[data-test="closure-action"]')
    expect(action.text()).toContain('Reiniciar os serviços')
    expect(action.get('[data-test="closure-done"]').text()).toBe('Já fiz')
    const missing = w.get('[data-test="closure-missing"]')
    expect(missing.text()).toContain('Tarefa 5 sem commit')
    expect(missing.find('[data-test="closure-done"]').exists()).toBe(false)
    expect(w.get('[data-test="closure-checked"]').text()).toContain('Verificado')
    expect(w.text()).toContain('Falta reiniciar')
  })

  it('Já fiz envia o item e troca a lista', async () => {
    setup('user_action', closure())
    const w = await mountBlock()
    await w.get('[data-test="closure-done"]').trigger('click')
    await flushPromises()
    expect(resolves).toEqual([{ item: 'Reiniciar os serviços' }])
    expect(w.find('[data-test="closure-action"]').exists()).toBe(false)
  })

  it('Pode fechar oferece Finalizar conversa', async () => {
    setup('can_close', closure({ verdict: 'can_close', user_actions: [], missing: [] }))
    const w = await mountBlock()
    expect(w.get('[data-test="closure-badge"]').text()).toBe('Pode fechar')
    await w.get('[data-test="closure-finish"]').trigger('click')
    await flushPromises()
    expect(patches).toEqual([{ finished: true }])
  })

  it('Pode fechar mantém Finalizar conversa quando a verificação deu erro ou não carregou', async () => {
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/sessions/s1/closure': () => jsonResponse({ detail: 'Falhou.' }, 500),
      'PATCH /api/sessions/s1': async (init?: RequestInit) => {
        patches.push(JSON.parse(String(init?.body)))
        return jsonResponse(makeSession({ finished: true, display_state: 'finished' }))
      },
    }))
    useSessionsStore().setForProject(1, [makeSession({ closure_verdict: 'can_close', display_state: 'waiting' })])
    const w = await mountBlock()
    expect(w.get('[data-test="closure-badge"]').text()).toBe('Pode fechar')
    await w.get('[data-test="closure-finish"]').trigger('click')
    await flushPromises()
    expect(patches).toEqual([{ finished: true }])
  })

  it('itens repetidos não repetem a chave', async () => {
    setup('user_action', closure({ user_actions: ['Reiniciar', 'Reiniciar'], missing: ['Falta X', 'Falta X'] }))
    const w = await mountBlock()
    expect(w.findAll('[data-test="closure-action"]')).toHaveLength(2)
    expect(w.findAll('[data-test="closure-missing"]')).toHaveLength(2)
  })

  it.each([
    ['vencido', null, closure()],
    ['em andamento', 'in_progress' as const, closure({ verdict: 'in_progress' })],
  ])('não aparece quando %s', async (_label, verdict, body) => {
    setup(verdict, body)
    const w = await mountBlock()
    expect(w.find('[data-test="details-closure"]').exists()).toBe(false)
  })

  it('não aparece em sessão finalizada', async () => {
    setup('can_close', closure({ verdict: 'can_close', user_actions: [], missing: [] }), 'finished')
    const w = await mountBlock()
    expect(w.find('[data-test="details-closure"]').exists()).toBe(false)
  })

  it('mostra o erro mesmo sem veredito', async () => {
    setup(null, closure({ verdict: null, user_actions: [], missing: [], error: 'O agente demorou demais para responder.' }))
    const w = await mountBlock()
    const error = w.get('[data-test="closure-error"]')
    expect(error.attributes('role')).toBe('alert')
    expect(error.text()).toBe('O agente demorou demais para responder.')
  })
})
