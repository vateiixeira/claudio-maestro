import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import { createAppRouter } from '../../../router'
import SessionRow from '../SessionRow.vue'
import { useProjectsStore } from '../../../stores/projects'
import { jsonResponse, makeProject, makeSession, routeFetch } from '../../../test/factories'

function mountRow(available: boolean) {
  const pinia = createPinia()
  setActivePinia(pinia)
  useProjectsStore(pinia).projects = [makeProject({ id: 1, available })]
  const router = createAppRouter(createMemoryHistory())
  return mount(SessionRow, {
    props: { session: makeSession({ session_id: 's1', project_id: 1 }), showProject: true },
    global: { plugins: [pinia, router] },
  })
}

describe('linha de sessão', () => {
  it('marca a pasta indisponível do projeto', () => {
    expect(mountRow(false).find('[data-test="project-unavailable"]').text()).toBe('pasta indisponível')
  })

  it('sem marca quando a pasta existe', () => {
    expect(mountRow(true).find('[data-test="project-unavailable"]').exists()).toBe(false)
  })
})

describe('permissão pendente na linha', () => {
  const pending = { prompt_id: 'p1', tool_name: 'Bash', summary: 'docker compose exec pagamentos pytest', can_allow_always: true }
  let calls: unknown[]
  let answerStatus: number
  afterEach(() => vi.unstubAllGlobals())

  function mountPending(overrides: Record<string, unknown> = {}) {
    const pinia = createPinia()
    setActivePinia(pinia)
    useProjectsStore(pinia).projects = [makeProject({ id: 1 })]
    const session = makeSession({ session_id: 's1', project_id: 1, awaiting_decision: true, pending_permission: pending, ...overrides })
    calls = []
    answerStatus = 200
    vi.stubGlobal('fetch', routeFetch({
      'POST /api/sessions/s1/prompts/p1': (init) => {
        calls.push(JSON.parse(init!.body as string))
        return answerStatus === 200 ? jsonResponse({}) : jsonResponse({ detail: 'Falhou.' }, answerStatus)
      },
    }))
    const router = createAppRouter(createMemoryHistory())
    return mount(SessionRow, { props: { session, showProject: true }, global: { plugins: [pinia, router] } })
  }

  it('mostra ferramenta e resumo do pedido, com Permitir, Negar e o link', () => {
    const w = mountPending()
    const block = w.find('[data-test="pending-permission"]')
    expect(block.text()).toContain('Bash')
    expect(block.text()).toContain('docker compose exec pagamentos pytest')
    expect(w.find('[data-test="pending-allow"]').text()).toBe('Permitir')
    expect(w.find('[data-test="pending-deny"]').text()).toBe('Negar')
    expect(w.find('[data-test="open-session"]').exists()).toBe(true)
  })

  it('sem pedido de permissão (pergunta ou plano) só tem o link', () => {
    const w = mountPending({ pending_permission: null })
    expect(w.find('[data-test="pending-permission"]').exists()).toBe(false)
    expect(w.find('[data-test="open-session"]').exists()).toBe(true)
  })

  it('Permitir responde allow_once e desabilita os botões enquanto envia', async () => {
    const w = mountPending()
    await w.find('[data-test="pending-allow"]').trigger('click')
    expect(w.find('[data-test="pending-allow"]').attributes('disabled')).toBeDefined()
    expect(w.find('[data-test="pending-deny"]').attributes('disabled')).toBeDefined()
    await flushPromises()
    expect(calls).toEqual([{ decision: 'allow_once' }])
    expect(w.find('[data-test="pending-status"]').text()).toContain('Resposta enviada')
    expect(w.find('[data-test="pending-allow"]').exists()).toBe(false)
  })

  it('Negar responde deny', async () => {
    const w = mountPending()
    await w.find('[data-test="pending-deny"]').trigger('click')
    await flushPromises()
    expect(calls).toEqual([{ decision: 'deny' }])
  })

  it('falha mostra erro legível e reabilita os botões', async () => {
    const w = mountPending()
    answerStatus = 500
    await w.find('[data-test="pending-allow"]').trigger('click')
    await flushPromises()
    expect(w.find('[role="alert"]').text()).toContain('Falhou.')
    expect(w.find('[data-test="pending-allow"]').attributes('disabled')).toBeUndefined()
  })

  it('409 conta como resolvida, sem mensagem de erro', async () => {
    const w = mountPending()
    answerStatus = 409
    await w.find('[data-test="pending-allow"]').trigger('click')
    await flushPromises()
    expect(w.find('[role="alert"]').exists()).toBe(false)
    expect(w.find('[data-test="pending-allow"]').exists()).toBe(false)
  })

  it('um novo pedido reabre os botões', async () => {
    const w = mountPending()
    await w.find('[data-test="pending-allow"]').trigger('click')
    await flushPromises()
    await w.setProps({
      session: makeSession({ session_id: 's1', awaiting_decision: true, pending_permission: { ...pending, prompt_id: 'p2', summary: 'ls' } }),
    })
    expect(w.find('[data-test="pending-allow"]').exists()).toBe(true)
    expect(w.find('[data-test="pending-permission"]').text()).toContain('ls')
  })
})
