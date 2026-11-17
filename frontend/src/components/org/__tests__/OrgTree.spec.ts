import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import OrgTree from '../OrgTree.vue'
import { createAppRouter } from '../../../router'
import { useOrgStore } from '../../../stores/org'
import { useSessionsStore } from '../../../stores/sessions'
import { makeAgent, makeRoutine, makeRun, makeSession } from '../../../test/factories'

enableAutoUnmount(afterEach)
afterEach(() => vi.useRealTimers())
let pinia: Pinia

beforeEach(() => {
  // Tuesday 10:40 local time; only the clock is fake, so the promises of the tests still run.
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(new Date(2026, 10, 17, 10, 40))
  pinia = createPinia()
  setActivePinia(pinia)
  useOrgStore(pinia).loaded = true
})

async function mountTree(path = '/agentes/1') {
  const router = createAppRouter(createMemoryHistory())
  await router.push(path)
  await router.isReady()
  const wrapper = mount(OrgTree, { props: { projectId: 1 }, global: { plugins: [pinia, router] } })
  await flushPromises()
  return { wrapper, router }
}

describe('OrgTree', () => {
  it('agrupa filhos sob o chefe', async () => {
    useOrgStore(pinia).agents = [
      makeAgent({ id: 1, name: 'CTO', reports_to: null }),
      makeAgent({ id: 2, slug: 'dev', name: 'Dev', reports_to: 1 }),
      makeAgent({ id: 3, slug: 'rev', name: 'Revisor', reports_to: 2 }),
      makeAgent({ id: 4, slug: 'outro', name: 'Outro', project_id: 2 }),
    ]
    const { wrapper } = await mountTree()
    const nodes = wrapper.findAll('[data-test="org-node"]')
    expect(nodes.map((n) => n.attributes('data-agent-id'))).toEqual(['1', '2', '3'])
    const cto = nodes[0]!
    expect(cto.find(':scope > ul [data-agent-id="2"]').exists()).toBe(true)
    expect(cto.find(':scope > ul [data-agent-id="3"]').exists()).toBe(true)
    expect(wrapper.find('li > ul > li > ul [data-agent-id="3"]').exists()).toBe(true)
  })

  it('mostra descrição e contador de novidades', async () => {
    useOrgStore(pinia).agents = [makeAgent({ id: 1, description: 'Coordena o time', unseen: 3 })]
    const { wrapper } = await mountTree()
    expect(wrapper.get('[data-test="org-node-description"]').text()).toBe('Coordena o time')
    expect(wrapper.get('[data-test="org-node-unseen"]').text()).toContain('3')
  })

  it('escreve as novidades por extenso, no singular quando é uma só', async () => {
    useOrgStore(pinia).agents = [makeAgent({ id: 1, unseen: 6 }), makeAgent({ id: 2, slug: 'b', name: 'B', reports_to: 1, unseen: 1 })]
    const { wrapper } = await mountTree()
    expect(wrapper.get('[data-agent-id="1"] [data-test="org-node-unseen"]').text()).toBe('6 novidades')
    expect(wrapper.get('[data-agent-id="2"] [data-test="org-node-unseen"]').text()).toBe('1 novidade')
  })

  it('sem novidades e sem rotina com horário o canto diz sem rotina', async () => {
    useOrgStore(pinia).agents = [makeAgent({ id: 1 })]
    useOrgStore(pinia).routines = { 1: [makeRoutine({ agent_id: 1, enabled: false, schedules: [{ id: 1, days: '1234567', time: '18:40', last_fired_at: null }] }), makeRoutine({ id: 2, agent_id: 1, enabled: true, schedules: [] })] }
    const { wrapper } = await mountTree()
    expect(wrapper.get('[data-test="org-node-aside"]').text()).toBe('sem rotina')
    expect(wrapper.find('[data-test="org-node-unseen"]').exists()).toBe(false)
  })

  it('agente desligado com rotina ligada continua mostrando o próximo horário', async () => {
    useOrgStore(pinia).agents = [makeAgent({ id: 1, enabled: false })]
    useOrgStore(pinia).routines = { 1: [makeRoutine({ agent_id: 1, enabled: true, schedules: [{ id: 1, days: '1234567', time: '18:40', last_fired_at: null }] })] }
    const { wrapper } = await mountTree()
    expect(wrapper.get('[data-agent-id="1"] [data-test="org-node-aside"]').text()).toBe('hoje 18:40')
  })

  it('sem novidades o canto mostra o próximo horário da rotina ligada', async () => {
    useOrgStore(pinia).agents = [makeAgent({ id: 1 }), makeAgent({ id: 2, slug: 'b', name: 'B', reports_to: 1 })]
    useOrgStore(pinia).routines = { 1: [
      makeRoutine({ agent_id: 1, enabled: true, schedules: [{ id: 1, days: '1234567', time: '18:40', last_fired_at: null }] }),
      makeRoutine({ id: 2, agent_id: 2, enabled: true, schedules: [{ id: 2, days: '123456', time: '08:40', last_fired_at: null }] }),
    ] }
    const { wrapper } = await mountTree()
    expect(wrapper.get('[data-agent-id="1"] [data-test="org-node-aside"]').text()).toBe('hoje 18:40')
    expect(wrapper.get('[data-agent-id="2"] [data-test="org-node-aside"]').text()).toBe('amanhã 08:40')
  })

  it('com novidades o canto mostra só as novidades', async () => {
    useOrgStore(pinia).agents = [makeAgent({ id: 1, unseen: 2 })]
    useOrgStore(pinia).routines = { 1: [makeRoutine({ agent_id: 1, schedules: [{ id: 1, days: '1234567', time: '18:40', last_fired_at: null }] })] }
    const { wrapper } = await mountTree()
    expect(wrapper.get('[data-test="org-node-aside"]').text()).toBe('2 novidades')
  })

  it('escreve o estado quando não é ocioso e mantém o ícone', async () => {
    useOrgStore(pinia).agents = [
      makeAgent({ id: 1, name: 'A', enabled: false }),
      makeAgent({ id: 2, slug: 'b', name: 'B', busy: true }),
      makeAgent({ id: 3, slug: 'c', name: 'C', last_run: makeRun({ agent_id: 3, outcome: 'waiting' }) }),
      makeAgent({ id: 4, slug: 'd', name: 'D' }),
    ]
    const { wrapper } = await mountTree()
    const text = (id: number) => wrapper.find(`[data-agent-id="${id}"] [data-test="org-node-state"]`)
    expect(text(1).text()).toBe('desligado')
    expect(wrapper.get('[data-agent-id="1"] [data-test="agent-state"]').attributes('data-state')).toBe('off')
    expect(text(2).text()).toBe('executando')
    expect(text(3).text()).toBe('aguardando você')
    expect(text(4).exists()).toBe(false)
    expect(wrapper.find('[data-agent-id="4"] [data-test="agent-state"]').exists()).toBe(true)
  })

  it('mostra o histórico das execuções que terminaram e nada sem execuções', async () => {
    useOrgStore(pinia).agents = [makeAgent({ id: 1 }), makeAgent({ id: 2, slug: 'b', name: 'B', reports_to: 1 })]
    useOrgStore(pinia).runs = {
      1: [
        makeRun({ id: 3, agent_id: 1, outcome: 'concluded', ended_at: 1_790_000_300 }),
        makeRun({ id: 2, agent_id: 1, outcome: 'failed', ended_at: 1_790_000_200 }),
        makeRun({ id: 1, agent_id: 1, outcome: 'concluded', ended_at: 1_790_000_100 }),
      ],
    }
    const { wrapper } = await mountTree()
    expect(wrapper.get('[data-agent-id="1"] [data-test="run-history"]').findAll('[data-test="run-history-bar"]')).toHaveLength(3)
    expect(wrapper.find('[data-agent-id="2"] [data-test="run-history"]').exists()).toBe(false)
  })

  it('agente com erro de definição mostra aviso', async () => {
    useOrgStore(pinia).agents = [makeAgent({ id: 1, definition_error: 'Falta o campo name na linha 2.' })]
    const { wrapper } = await mountTree()
    const warning = wrapper.get('[data-test="org-node-definition-error"]')
    expect(warning.attributes('title')).toBe('Falta o campo name na linha 2.')
    expect(warning.text()).toContain('Definição inválida')
  })

  it('estado aguardando usa triângulo', async () => {
    useOrgStore(pinia).agents = [
      makeAgent({ id: 1, name: 'A', last_run: makeRun({ agent_id: 1, outcome: 'waiting' }) }),
      makeAgent({ id: 2, slug: 'b', name: 'B', busy: true }),
      makeAgent({ id: 3, slug: 'c', name: 'C' }),
      makeAgent({ id: 4, slug: 'd', name: 'D', enabled: false }),
    ]
    const { wrapper } = await mountTree()
    const state = (id: number) => wrapper.get(`[data-agent-id="${id}"] [data-test="agent-state"]`)
    expect(state(1).attributes('data-state')).toBe('waiting')
    expect(state(1).attributes('data-shape')).toBe('triangle')
    expect(state(1).attributes('aria-label')).toBe('Aguardando você')
    expect(state(2).attributes('data-state')).toBe('busy')
    expect(state(2).attributes('aria-label')).toBe('Executando')
    expect(state(2).attributes('data-shape')).toBe('spinner')
    expect(state(3).attributes('data-state')).toBe('idle')
    expect(state(3).attributes('data-shape')).toBe('circle')
    expect(state(4).attributes('data-state')).toBe('off')
    expect(state(4).attributes('data-shape')).toBe('dashed')
  })

  it('o estado do agente vem da conversa principal quando ela pede resposta', async () => {
    useOrgStore(pinia).agents = [makeAgent({ id: 1, main_session_id: 'main' })]
    useSessionsStore(pinia).setForProject(1, [makeSession({ session_id: 'main', pending_kind: 'tool' })])
    const { wrapper } = await mountTree()
    expect(wrapper.get('[data-test="agent-state"]').attributes('data-state')).toBe('waiting')
  })

  it('clicar escolhe o agente pela query e marca aria-current', async () => {
    useOrgStore(pinia).agents = [makeAgent({ id: 1 }), makeAgent({ id: 2, slug: 'dev', name: 'Dev', reports_to: 1 })]
    const { wrapper, router } = await mountTree()
    await wrapper.get('[data-agent-id="2"] [data-test="org-node-button"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.query.agente).toBe('2')
    expect(wrapper.get('[data-agent-id="2"] [data-test="org-node-button"]').attributes('aria-current')).toBe('true')
    expect(wrapper.get('[data-agent-id="1"] [data-test="org-node-button"]').attributes('aria-current')).toBeUndefined()
  })

  it('lê o agente selecionado da query', async () => {
    useOrgStore(pinia).agents = [makeAgent({ id: 1 }), makeAgent({ id: 2, slug: 'dev', name: 'Dev', reports_to: 1 })]
    const { wrapper } = await mountTree('/agentes/1?agente=2')
    expect(wrapper.get('[data-agent-id="2"] [data-test="org-node-button"]').attributes('aria-current')).toBe('true')
  })

  it('sem agentes mostra o convite e o botão', async () => {
    const { wrapper } = await mountTree()
    expect(wrapper.get('[data-test="org-tree-empty"]').text()).toContain('Nenhum agente ainda. Crie o primeiro: um CTO para este projeto.')
    await wrapper.get('[data-test="org-tree-create"]').trigger('click')
    expect(wrapper.emitted('create')).toHaveLength(1)
  })
})
