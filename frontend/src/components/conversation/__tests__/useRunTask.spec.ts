import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { defineComponent, ref } from 'vue'
import { useRunTask } from '../useRunTask'
import { useOrgStore } from '../../../stores/org'
import { useSessionsStore } from '../../../stores/sessions'
import { jsonResponse, makeAgent, makeRun, makeSession, routeFetch } from '../../../test/factories'

enableAutoUnmount(afterEach)
let pinia: Pinia

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  useOrgStore(pinia).agents = [makeAgent({ id: 4, name: 'Triagem', main_session_id: 'main' })]
})
afterEach(() => vi.unstubAllGlobals())

function host(id = 's1') {
  const sessionId = ref(id)
  let result!: ReturnType<typeof useRunTask>
  mount(defineComponent({ setup() { result = useRunTask(sessionId); return () => null } }), { global: { plugins: [pinia] } })
  return { sessionId, result }
}
const session = (extra = {}) => useSessionsStore(pinia).setForProject(1, [makeSession({ session_id: 's1', agent_id: 4, ...extra })])

describe('useRunTask', () => {
  it('devolve o agente e a tarefa da execução já carregada, sem buscar de novo', () => {
    const fetch = routeFetch({})
    vi.stubGlobal('fetch', fetch)
    useOrgStore(pinia).runs = { 4: [makeRun({ id: 7, agent_id: 4, session_id: 's1', task_id: 9 })] }
    session()
    const { result } = host()
    expect(result.agentId.value).toBe(4)
    expect(result.agent.value?.name).toBe('Triagem')
    expect(result.taskId.value).toBe(9)
    expect(fetch).not.toHaveBeenCalled()
  })

  it('carrega as execuções do agente quando ainda não estão carregadas', async () => {
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/agents/4/runs?limit=50': () => jsonResponse([makeRun({ id: 7, agent_id: 4, session_id: 's1', task_id: 9 })]),
    }))
    session()
    const { result } = host()
    expect(result.taskId.value).toBeNull()
    await flushPromises()
    expect(result.taskId.value).toBe(9)
  })

  it('a falha ao carregar só esconde a tarefa', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/agents/4/runs?limit=50': () => jsonResponse({ detail: 'x' }, 500) }))
    session()
    const { result } = host()
    await flushPromises()
    expect(result.agentId.value).toBe(4)
    expect(result.taskId.value).toBeNull()
  })

  it('a conversa principal, a comum e a execução sem tarefa não têm tarefa nem buscam', async () => {
    const fetch = routeFetch({})
    vi.stubGlobal('fetch', fetch)
    session({ session_id: 's1' })
    useOrgStore(pinia).agents = [makeAgent({ id: 4, main_session_id: 's1' })]
    const main = host()
    expect(main.result.agentId.value).toBeNull()
    expect(main.result.taskId.value).toBeNull()
    useSessionsStore(pinia).setForProject(1, [makeSession({ session_id: 's1', agent_id: null })])
    useOrgStore(pinia).agents = [makeAgent({ id: 4, main_session_id: 'main' })]
    expect(host().result.agentId.value).toBeNull()
    await flushPromises()
    expect(fetch).not.toHaveBeenCalled()
    useOrgStore(pinia).runs = { 4: [makeRun({ id: 8, agent_id: 4, session_id: 's1', task_id: null })] }
    session()
    expect(host().result.taskId.value).toBeNull()
  })

  it('acompanha a troca de conversa', () => {
    useOrgStore(pinia).runs = { 4: [makeRun({ id: 7, agent_id: 4, session_id: 's1', task_id: 9 }), makeRun({ id: 8, agent_id: 4, session_id: 's2', task_id: 12 })] }
    useSessionsStore(pinia).setForProject(1, [makeSession({ session_id: 's1', agent_id: 4 }), makeSession({ session_id: 's2', agent_id: 4 })])
    const { sessionId, result } = host('s1')
    expect(result.taskId.value).toBe(9)
    sessionId.value = 's2'
    expect(result.taskId.value).toBe(12)
  })
})
