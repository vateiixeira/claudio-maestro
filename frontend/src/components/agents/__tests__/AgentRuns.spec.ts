import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import { createAppRouter } from '../../../router'
import { jsonResponse, makeSpecialistRun, routeFetch } from '../../../test/factories'
import AgentRuns from '../AgentRuns.vue'

enableAutoUnmount(afterEach)
beforeEach(() => setActivePinia(createPinia()))
afterEach(() => vi.unstubAllGlobals())
it('separa a fila do histórico e filtra problemas sem esconder os pedidos pendentes', async () => {
  vi.stubGlobal('fetch', routeFetch({
    'GET /api/specialists/1/runs?limit=50': () => jsonResponse([
      makeSpecialistRun({ id: 1, outcome: 'queued', session_id: null }),
      makeSpecialistRun({ id: 2, outcome: 'concluded', session_id: 'done' }),
      makeSpecialistRun({ id: 3, outcome: 'failed', reason: 'Acesso indisponível', session_id: 'error' }),
      makeSpecialistRun({ id: 4, trigger: 'comment', outcome: 'concluded', session_id: 'comment' }),
    ]),
  }))
  const router = createAppRouter(createMemoryHistory())
  await router.push('/agentes/1?aba=runs')
  const w = mount(AgentRuns, { props: { agentId: 1 }, global: { plugins: [router] } })
  await flushPromises()
  expect(w.get('[aria-label="Fila de execução"]').findAll('[data-test="run-row"]')).toHaveLength(1)
  expect(w.get('[aria-label="Histórico de execuções"]').text()).toContain('Comentário de PR')
  await w.get('[data-test="run-filter-problems"]').trigger('click')
  const history = w.get('[aria-label="Histórico de execuções"]')
  expect(history.findAll('[data-test="run-row"]')).toHaveLength(1)
  expect(history.text()).toContain('Acesso indisponível')
  expect(w.find('[data-test="run-cancel"]').exists()).toBe(true)
})
