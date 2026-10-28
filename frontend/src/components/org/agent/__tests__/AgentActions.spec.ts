import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import AgentActions from '../AgentActions.vue'
import { createAppRouter } from '../../../../router'
import { useOrgStore } from '../../../../stores/org'
import { useProjectsStore } from '../../../../stores/projects'
import { jsonResponse, makeAgent, makeProject, routeFetch } from '../../../../test/factories'
import type { Agent } from '../../../../types/org'

enableAutoUnmount(afterEach)
let pinia: Pinia
beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
})
afterEach(() => vi.unstubAllGlobals())

type Handlers = Parameters<typeof routeFetch>[0]

async function mountActions(agent: Partial<Agent> = {}, handlers: Handlers = {}) {
  const org = useOrgStore(pinia)
  org.agents = [
    makeAgent({ id: 1, name: 'CTO' }),
    makeAgent({ id: 2, slug: 'dev', name: 'Dev', reports_to: 1, ...agent }),
    makeAgent({ id: 3, slug: 'rev', name: 'Revisor', reports_to: 2 }),
    makeAgent({ id: 4, slug: 'fora', name: 'De outro projeto', project_id: 9 }),
  ]
  const projects = useProjectsStore(pinia)
  projects.projects = [makeProject({ id: 1, name: 'Loja' }), makeProject({ id: 9, name: 'Blog' })]
  projects.loaded = true
  const fetch = routeFetch(handlers)
  vi.stubGlobal('fetch', fetch)
  const router = createAppRouter(createMemoryHistory())
  await router.push('/agentes/1?agente=2')
  await router.isReady()
  const wrapper = mount(AgentActions, { props: { agentId: 2 }, global: { plugins: [pinia, router] } })
  await flushPromises()
  return { wrapper, fetch, router, org }
}

const bodyOf = (fetch: ReturnType<typeof routeFetch>, method: string, url: string) => {
  const call = fetch.mock.calls.find(([u, init]) => u === url && init?.method === method)
  return call ? JSON.parse(String(call[1]?.body ?? 'null')) : undefined
}

describe('AgentActions', () => {
  it('rodar agora desabilitado com erro de definição', async () => {
    const { wrapper } = await mountActions({ definition_error: 'Falta o campo name.' })
    const run = wrapper.get('[data-test="agent-run"]')
    expect(run.attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-test="agent-run-blocked"]').text()).toContain('definição')
  })

  it('rodar agora desabilitado com o agente desligado', async () => {
    const { wrapper } = await mountActions({ enabled: false })
    expect(wrapper.get('[data-test="agent-run"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-test="agent-run-blocked"]').text()).toContain('desligado')
  })

  it('rodar agora pede a execução com a instrução e avisa', async () => {
    const { wrapper, fetch } = await mountActions({}, { 'POST /api/agents/2/wake': () => jsonResponse({ id: 5 }, 202) })
    await wrapper.get('[data-test="agent-run-text"]').setValue('Revise o PR 12')
    await wrapper.get('[data-test="agent-run"]').trigger('click')
    await flushPromises()
    expect(bodyOf(fetch, 'POST', '/api/agents/2/wake')).toEqual({ text: 'Revise o PR 12' })
    expect(wrapper.get('[data-test="agent-run-ok"]').text()).toContain('na fila')
    expect(wrapper.get<HTMLInputElement>('[data-test="agent-run-text"]').element.value).toBe('')
  })

  it('rodar agora sem instrução não manda texto', async () => {
    const { wrapper, fetch } = await mountActions({}, { 'POST /api/agents/2/wake': () => jsonResponse({ id: 5 }, 202) })
    await wrapper.get('[data-test="agent-run"]').trigger('click')
    await flushPromises()
    expect(bodyOf(fetch, 'POST', '/api/agents/2/wake')).toEqual({})
  })

  it('mostra o erro de rodar agora', async () => {
    const { wrapper } = await mountActions({}, { 'POST /api/agents/2/wake': () => jsonResponse({ detail: 'A fila do agente está cheia.' }, 409) })
    await wrapper.get('[data-test="agent-run"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-test="agent-error"]').attributes('role')).toBe('alert')
    expect(wrapper.get('[data-test="agent-error"]').text()).toContain('A fila do agente está cheia.')
  })

  it('desligar e ligar enviam o PATCH e atualizam o agente', async () => {
    const { wrapper, fetch, org } = await mountActions({}, {
      'PATCH /api/agents/2': () => jsonResponse(makeAgent({ id: 2, slug: 'dev', name: 'Dev', reports_to: 1, enabled: false })),
    })
    expect(wrapper.get('[data-test="agent-toggle"]').text()).toBe('Desligar')
    await wrapper.get('[data-test="agent-toggle"]').trigger('click')
    await flushPromises()
    expect(bodyOf(fetch, 'PATCH', '/api/agents/2')).toEqual({ enabled: false })
    expect(org.byId(2)?.enabled).toBe(false)
    expect(wrapper.get('[data-test="agent-toggle"]').text()).toBe('Ligar')
  })

  it('o select de chefe lista os agentes do projeto menos ele mesmo', async () => {
    const { wrapper } = await mountActions()
    const options = wrapper.findAll('[data-test="agent-boss"] option').map((o) => o.text())
    expect(options).toEqual(['Ninguém (topo)', 'CTO', 'Revisor'])
    expect(wrapper.get<HTMLSelectElement>('[data-test="agent-boss"]').element.value).toBe('1')
  })

  it('trocar chefe envia PATCH', async () => {
    const { wrapper, fetch, org } = await mountActions({}, {
      'PATCH /api/agents/2': () => jsonResponse(makeAgent({ id: 2, slug: 'dev', name: 'Dev', reports_to: null })),
    })
    await wrapper.get('[data-test="agent-boss"]').setValue('')
    await flushPromises()
    expect(bodyOf(fetch, 'PATCH', '/api/agents/2')).toEqual({ reports_to: null })
    expect(org.byId(2)?.reports_to).toBeNull()
  })

  it('trocar chefe mostra o 422 e volta ao chefe de antes', async () => {
    const { wrapper, fetch } = await mountActions({}, {
      'PATCH /api/agents/2': () => jsonResponse({ detail: 'Isso criaria um ciclo na organização.' }, 422),
    })
    await wrapper.get('[data-test="agent-boss"]').setValue('3')
    await flushPromises()
    expect(bodyOf(fetch, 'PATCH', '/api/agents/2')).toEqual({ reports_to: 3 })
    expect(wrapper.get('[data-test="agent-error"]').text()).toContain('ciclo')
    expect(wrapper.get('[data-test="agent-error"]').attributes('role')).toBe('alert')
    expect(wrapper.get<HTMLSelectElement>('[data-test="agent-boss"]').element.value).toBe('1')
  })

  it('duplica para outro projeto e abre a cópia na definição', async () => {
    const copy = makeAgent({ id: 10, slug: 'dev', name: 'Dev', project_id: 9 })
    const { wrapper, fetch, router, org } = await mountActions({}, { 'POST /api/agents/2/duplicate': () => jsonResponse(copy, 201) })
    await wrapper.get('[data-test="agent-duplicate"]').trigger('click')
    expect(wrapper.get<HTMLInputElement>('[data-test="duplicate-slug"]').element.value).toBe('dev')
    await wrapper.get('[data-test="duplicate-project"]').setValue('9')
    await wrapper.get('[data-test="confirm-ok"]').trigger('click')
    await flushPromises()
    expect(bodyOf(fetch, 'POST', '/api/agents/2/duplicate')).toEqual({ project_id: 9, slug: 'dev' })
    expect(org.byId(10)?.project_id).toBe(9)
    expect(router.currentRoute.value.fullPath).toBe('/agentes/9?agente=10&aba=definicao')
    expect(wrapper.find('[data-test="duplicate-slug"]').exists()).toBe(false)
  })

  it('duplicar mostra o erro dentro do diálogo e mantém o diálogo aberto', async () => {
    const { wrapper } = await mountActions({}, { 'POST /api/agents/2/duplicate': () => jsonResponse({ detail: 'Já existe um agente com esse identificador.' }, 409) })
    await wrapper.get('[data-test="agent-duplicate"]').trigger('click')
    await wrapper.get('[data-test="confirm-ok"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-test="duplicate-error"]').attributes('role')).toBe('alert')
    expect(wrapper.get('[data-test="duplicate-error"]').text()).toContain('Já existe')
    expect(wrapper.find('[data-test="duplicate-slug"]').exists()).toBe(true)
  })

  it('duplicar com identificador inválido não envia', async () => {
    const { wrapper } = await mountActions()
    await wrapper.get('[data-test="agent-duplicate"]').trigger('click')
    await wrapper.get('[data-test="duplicate-slug"]').setValue('Nome Ruim')
    expect(wrapper.get('[data-test="confirm-ok"]').attributes('disabled')).toBeDefined()
  })

  it('excluir pede confirmação, apaga e avisa o painel', async () => {
    const { wrapper, fetch, org } = await mountActions({}, { 'DELETE /api/agents/2': () => jsonResponse(undefined, 204) })
    await wrapper.get('[data-test="agent-delete"]').trigger('click')
    expect(wrapper.get('[role="dialog"]').text()).toContain('Dev')
    await wrapper.get('[data-test="confirm-ok"]').trigger('click')
    await flushPromises()
    expect(fetch.mock.calls.some(([u, init]) => u === '/api/agents/2' && init?.method === 'DELETE')).toBe(true)
    expect(wrapper.emitted('deleted')).toHaveLength(1)
    expect(org.byId(2)).toBeUndefined()
  })

  it('cancelar a confirmação não apaga', async () => {
    const { wrapper, fetch } = await mountActions()
    await wrapper.get('[data-test="agent-delete"]').trigger('click')
    await wrapper.get('[data-test="confirm-cancel"]').trigger('click')
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    expect(fetch).not.toHaveBeenCalled()
  })

  it('excluir um agente ocupado mostra o motivo e continua listado', async () => {
    const { wrapper, org } = await mountActions({}, { 'DELETE /api/agents/2': () => jsonResponse({ detail: 'O agente está executando.' }, 409) })
    await wrapper.get('[data-test="agent-delete"]').trigger('click')
    await wrapper.get('[data-test="confirm-ok"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    expect(wrapper.get('[data-test="agent-error"]').text()).toContain('O agente está executando.')
    expect(wrapper.emitted('deleted')).toBeUndefined()
    expect(org.byId(2)).toBeDefined()
  })
})
