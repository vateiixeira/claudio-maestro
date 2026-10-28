import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import OrgTree from '../OrgTree.vue'
import { createAppRouter } from '../../../router'
import { useOrgStore } from '../../../stores/org'
import { useSessionsStore } from '../../../stores/sessions'
import { makeAgent, makeRun, makeSession } from '../../../test/factories'

enableAutoUnmount(afterEach)
let pinia: Pinia

beforeEach(() => {
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
