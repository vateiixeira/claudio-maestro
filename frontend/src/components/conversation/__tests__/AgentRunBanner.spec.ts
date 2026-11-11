import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import AgentRunBanner from '../AgentRunBanner.vue'
import { createAppRouter } from '../../../router'
import { useOrgStore } from '../../../stores/org'
import { useSessionsStore } from '../../../stores/sessions'
import { makeAgent, makeRun, makeSession } from '../../../test/factories'

enableAutoUnmount(afterEach)
let pinia: Pinia

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
})

async function mountBanner(sessionId = 'main') {
  const router = createAppRouter(createMemoryHistory())
  await router.push(`/sessions/${sessionId}`)
  await router.isReady()
  const wrapper = mount(AgentRunBanner, { props: { sessionId }, global: { plugins: [pinia, router] } })
  await flushPromises()
  return wrapper
}

function setup(runOutcome: 'running' | 'waiting' = 'running', runSession: Partial<ReturnType<typeof makeSession>> = {}) {
  useOrgStore(pinia).agents = [
    makeAgent({ id: 1, main_session_id: 'main', busy: true, last_run: makeRun({ outcome: runOutcome, session_id: 'run' }) }),
  ]
  useSessionsStore(pinia).setForProject(1, [
    makeSession({ session_id: 'main', agent_id: 1 }),
    makeSession({ session_id: 'run', agent_id: 1, title: 'Revisar o PR 42', state: 'running', ...runSession }),
  ])
}

describe('AgentRunBanner', () => {
  it('mostra o run em andamento e leva à sessão dele', async () => {
    setup()
    const w = await mountBanner()
    const banner = w.get('[data-test="agent-run-banner"]')
    expect(banner.attributes('data-state')).toBe('running')
    expect(banner.text()).toContain('Rodando agora: Revisar o PR 42')
    expect(w.get('[data-test="agent-state"]').attributes('data-state')).toBe('busy')
    expect(banner.attributes('href')).toBe('/sessions/run')
  })

  it('fica no tom de espera quando a sessão pede resposta', async () => {
    setup('running', { pending_kind: 'question' })
    const w = await mountBanner()
    const banner = w.get('[data-test="agent-run-banner"]')
    expect(banner.attributes('data-state')).toBe('waiting')
    expect(banner.text()).toContain('Revisar o PR 42 espera sua resposta')
    expect(banner.text()).not.toContain('Rodando agora')
    expect(w.get('[data-test="agent-state"]').attributes('data-state')).toBe('waiting')
    expect(banner.classes().join(' ')).toContain('secondary')
  })

  it('fica no tom de espera quando o run está em waiting', async () => {
    setup('waiting')
    const w = await mountBanner()
    expect(w.get('[data-test="agent-run-banner"]').attributes('data-state')).toBe('waiting')
  })

  it('não aparece fora da conversa principal de um agente', async () => {
    setup()
    const w = await mountBanner('run')
    expect(w.find('[data-test="agent-run-banner"]').exists()).toBe(false)
  })

  it('some quando o run termina e volta com o próximo', async () => {
    setup()
    const w = await mountBanner()
    expect(w.find('[data-test="agent-run-banner"]').exists()).toBe(true)
    const org = useOrgStore(pinia)
    org.agents = [{ ...org.agents[0]!, busy: false, last_run: makeRun({ outcome: 'concluded', session_id: 'run' }) }]
    useSessionsStore(pinia).setForProject(1, [
      makeSession({ session_id: 'main', agent_id: 1 }),
      makeSession({ session_id: 'run', agent_id: 1, title: 'Revisar o PR 42', state: 'closed' }),
    ])
    await flushPromises()
    expect(w.find('[data-test="agent-run-banner"]').exists()).toBe(false)
    org.agents = [{ ...org.agents[0]!, busy: true, last_run: makeRun({ id: 2, outcome: 'running', session_id: 'run2' }) }]
    useSessionsStore(pinia).setForProject(1, [
      makeSession({ session_id: 'main', agent_id: 1 }),
      makeSession({ session_id: 'run2', agent_id: 1, title: 'Outra rotina', state: 'running' }),
    ])
    await flushPromises()
    expect(w.get('[data-test="agent-run-banner"]').text()).toContain('Rodando agora: Outra rotina')
    expect(w.get('[data-test="agent-run-banner"]').attributes('href')).toBe('/sessions/run2')
  })
})
