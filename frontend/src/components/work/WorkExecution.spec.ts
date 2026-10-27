import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { mount, flushPromises, enableAutoUnmount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import { createAppRouter } from '../../router'
import CoordinatorWork from './CoordinatorWork.vue'
import DecisionRequest from './DecisionRequest.vue'
import AttemptResult from './AttemptResult.vue'
import { jsonResponse, routeFetch } from '../../test/factories'
import type { WorkAttempt } from '../../types/work'
enableAutoUnmount(afterEach)
beforeEach(() => setActivePinia(createPinia()))
afterEach(() => vi.unstubAllGlobals())
it('uma decisão respondida não reapresenta formulário para novo envio', () => {
  const wrapper = mount(DecisionRequest, { props: { decision: { id: 1, revision: 2, status: 'answered', work_item_id: 1, attempt_id: 2, request: { question: 'Publicar?', action: 'deploy' }, answer: { answer: 'Não publicar' } } } })
  expect(wrapper.find('form').exists()).toBe(false)
  expect(wrapper.text()).toContain('Não publicar')
})
it('tentativas históricas mostram apenas o resultado de sua própria rodada', async () => {
  const router = createAppRouter(createMemoryHistory()); await router.push('/cto?projeto=1')
  const attempt = { id: 1, work_item_id: 1, session_id: 'old-worker', role: 'investigator', state: 'succeeded', work_revision: 1, created_at: 10, updated_at: 20, ended_at: 20, result_kind: 'investigation', result: { summary: 'Resultado histórico exato' } } satisfies WorkAttempt
  const wrapper = mount(AttemptResult, { props: { attempt, live: true }, global: { plugins: [router], stubs: { AgentExecutionDetail: { template: '<p data-test="live-child">Resultado vivo diferente</p>' } } } })
  expect(wrapper.find('[data-test="live-child"]').exists()).toBe(false)
  expect(wrapper.text()).toContain('Resultado histórico exato')
})
it('CTO inclui tarefas e tentativas próprias com execução ao vivo e resultado anterior', async () => {
  const attempt = (id: number, state: string) => ({ id, work_item_id: 4, session_id: `worker-${id}`, role: 'investigator', state, work_revision: 1, created_at: 1, updated_at: 2, ended_at: state === 'running' ? null : 2, result: state === 'running' ? null : { summary: 'Análise da tentativa anterior' } })
  vi.stubGlobal('fetch', routeFetch({
    'GET /api/work-items?project_id=1&limit=12&offset=0': () => jsonResponse({ items: [{ id: 4 }], total: 1, limit: 12, offset: 0 }),
    'GET /api/work-items/4': () => jsonResponse({ item: { id: 4, project_id: 1, title: 'Corrigir pagamento', status: 'active', source: 'manual' }, dossier: {}, attempts: [attempt(1, 'succeeded'), attempt(2, 'running')], events: [] }),
    'GET /api/work/decisions?pending_only=true&project_id=1': () => jsonResponse({ items: [] }),
    'GET /api/projects/1/work-feed?latest=true': () => jsonResponse({ items: [], after: 0 }),
  }))
  const router = createAppRouter(createMemoryHistory()); await router.push('/cto?projeto=1')
  const wrapper = mount(CoordinatorWork, { props: { projectId: 1 }, global: { plugins: [router], stubs: { AgentExecutionDetail: { props: ['sessionId'], template: '<p data-test="live-child">{{ sessionId }}</p>' } } } })
  await flushPromises()
  expect(wrapper.text()).toContain('Corrigir pagamento')
  expect(wrapper.text()).toContain('Análise da tentativa anterior')
  expect(wrapper.findAll('[data-test="live-child"]')).toHaveLength(1)
  expect(wrapper.get('[data-test="live-child"]').text()).toBe('worker-2')
})
