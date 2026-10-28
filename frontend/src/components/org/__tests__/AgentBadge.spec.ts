import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { enableAutoUnmount, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import AgentBadge from '../AgentBadge.vue'
import { useOrgStore } from '../../../stores/org'
import { makeAgent } from '../../../test/factories'

enableAutoUnmount(afterEach)
let pinia: Pinia
beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
})

describe('AgentBadge', () => {
  it('mostra "Agente · nome" quando o agente está carregado', () => {
    useOrgStore(pinia).agents = [makeAgent({ id: 4, name: 'Triagem' })]
    const w = mount(AgentBadge, { props: { agentId: 4 }, global: { plugins: [pinia] } })
    expect(w.get('[data-test="agent-badge"]').text()).toBe('Agente · Triagem')
  })

  it('agente não carregado ou apagado mostra só "Agente"', () => {
    const w = mount(AgentBadge, { props: { agentId: 9 }, global: { plugins: [pinia] } })
    expect(w.get('[data-test="agent-badge"]').text()).toBe('Agente')
  })
})
