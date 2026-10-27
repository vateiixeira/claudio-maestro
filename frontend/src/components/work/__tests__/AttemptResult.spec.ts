import { afterEach, expect, it } from 'vitest'
import { mount, enableAutoUnmount } from '@vue/test-utils'
import AttemptResult from '../AttemptResult.vue'
import type { WorkAttempt } from '../../../types/work'
enableAutoUnmount(afterEach)
const attempt = (overrides: Partial<WorkAttempt> = {}): WorkAttempt => ({ id: 4, work_item_id: 1, session_id: 'old-session', role: 'investigator', state: 'succeeded', work_revision: 2, created_at: 100, updated_at: 200, ended_at: 200, result_kind: 'investigation', result: { summary: 'Resultado histórico', tests: ['pytest passou', { command: 'pytest backend/tests/test_x.py', executed: true, status: 'passed', output_ref: 'tool-1', execution_verified: true }, { command: 'pnpm test', executed: false, status: 'not_run', output_ref: '', execution_verified: false }] }, ...overrides })
it('separa testes com registro de execução de relatos e testes não executados', () => {
  const wrapper = mount(AttemptResult, { props: { attempt: attempt() }, global: { stubs: { RouterLink: true, AgentExecutionDetail: true } } })
  const rows = wrapper.findAll('[data-test="test-evidence"]')
  expect(rows).toHaveLength(3)
  expect(rows[0]!.text()).toContain('Execução não comprovada')
  expect(rows[1]!.text()).toContain('Passou, execução registrada')
  expect(rows[2]!.text()).toContain('Não executado')
})
it('tentativa histórica mostra seu resultado e nunca monta a execução ao vivo', () => {
  const wrapper = mount(AttemptResult, { props: { attempt: attempt(), live: true }, global: { stubs: { RouterLink: true, AgentExecutionDetail: true } } })
  expect(wrapper.get('[data-test="attempt-result"]').text()).toBe('Resultado histórico')
  expect(wrapper.find('agent-execution-detail-stub').exists()).toBe(false)
})
it('preserva a declaração explícita de teste não rodado após normalização do backend', () => {
  const wrapper = mount(AttemptResult, { props: { attempt: attempt({ result: { summary: 'Análise', tests: [{ command: 'pytest', executed: false, status: 'unverified', declared_executed: false, declared_status: 'not_run', execution_verified: false }] } }) }, global: { stubs: { RouterLink: true, AgentExecutionDetail: true } } })
  expect(wrapper.get('[data-test="test-evidence"]').text()).toContain('Não executado (informado pelo executor)')
})
