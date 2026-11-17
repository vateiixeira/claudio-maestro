import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import AgentHeader from '../AgentHeader.vue'
import { createAppRouter } from '../../../../router'
import { useOrgStore } from '../../../../stores/org'
import { useProjectsStore } from '../../../../stores/projects'
import { jsonResponse, makeAgent, makeProject, makeRoutine, routeFetch } from '../../../../test/factories'
import type { Agent, Routine } from '../../../../types/org'

enableAutoUnmount(afterEach)
let pinia: Pinia
beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  // Tuesday 2026-11-17, 10:40.
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(new Date(2026, 10, 17, 10, 40))
})
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})

type Handlers = Parameters<typeof routeFetch>[0]

const EVERY_DAY_1840 = [{ id: 1, days: '1234567', time: '18:40', last_fired_at: null }]

async function mountHeader(agent: Partial<Agent> = {}, handlers: Handlers = {}, routines: Routine[] = []) {
  const org = useOrgStore(pinia)
  org.agents = [
    makeAgent({ id: 1, name: 'Maestro' }),
    makeAgent({ id: 2, slug: 'dev', name: 'Dev', reports_to: 1, ...agent }),
    makeAgent({ id: 3, slug: 'rev', name: 'Revisor', reports_to: 2 }),
    makeAgent({ id: 4, slug: 'fora', name: 'De outro projeto', project_id: 9 }),
  ]
  const projects = useProjectsStore(pinia)
  projects.projects = [makeProject({ id: 1, name: 'Loja' }), makeProject({ id: 9, name: 'Blog' }), makeProject({ id: 99, name: 'Sem projeto', path: '/home/vi/.local/share/claudio-maestro/scratch', kind: 'scratch', position: 99 })]
  projects.loaded = true
  const fetch = routeFetch({ 'GET /api/routines?project_id=1': () => jsonResponse(routines), ...handlers })
  vi.stubGlobal('fetch', fetch)
  const router = createAppRouter(createMemoryHistory())
  await router.push('/agentes/1?agente=2')
  await router.isReady()
  const wrapper = mount(AgentHeader, { props: { agentId: 2 }, global: { plugins: [pinia, router] } })
  await flushPromises()
  return { wrapper, fetch, router, org }
}

const bodyOf = (fetch: ReturnType<typeof routeFetch>, method: string, url: string) => {
  const call = fetch.mock.calls.find(([u, init]) => u === url && init?.method === method)
  return call ? JSON.parse(String(call[1]?.body ?? 'null')) : undefined
}

const menuItem = (id: string) => document.body.querySelector<HTMLElement>(`[data-test="more-menu-item"][data-id="${id}"]`)
async function choose(wrapper: Awaited<ReturnType<typeof mountHeader>>['wrapper'], id: string) {
  await wrapper.get('[data-test="agent-more"]').trigger('click')
  await flushPromises()
  menuItem(id)!.click()
  await flushPromises()
}

describe('AgentHeader', () => {
  it('mostra nome, descrição, modelo, esforço e o chefe', async () => {
    const { wrapper, router } = await mountHeader({ model: 'sonnet', effort: 'high', description: 'Faz as tarefas' })
    expect(wrapper.attributes('data-test')).toBe('agent-header')
    expect(wrapper.get('h2').text()).toBe('Dev')
    expect(wrapper.get('[data-test="agent-description"]').text()).toBe('Faz as tarefas')
    expect(wrapper.get('[data-test="agent-model"]').text()).toBe('Sonnet')
    expect(wrapper.get('[data-test="agent-effort"]').text()).toBe('high')
    expect(wrapper.text()).toContain('responde ao Maestro')
    const boss = wrapper.get('[data-test="agent-boss-link"]')
    expect(boss.text()).toBe('Maestro')
    await boss.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.fullPath).toBe('/agentes/1?agente=1')
  })

  it('agente do topo não mostra o "responde ao"', async () => {
    const { wrapper } = await mountHeader({ reports_to: null })
    expect(wrapper.text()).not.toContain('responde ao')
    expect(wrapper.find('[data-test="agent-boss-link"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="agent-model"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="agent-effort"]').exists()).toBe(false)
  })

  it('o ícone de estado só aparece executando ou esperando você', async () => {
    const idle = await mountHeader()
    expect(idle.wrapper.find('[data-test="agent-state"]').exists()).toBe(false)
    idle.org.upsertAgent(makeAgent({ id: 2, slug: 'dev', name: 'Dev', reports_to: 1, busy: true }))
    await flushPromises()
    expect(idle.wrapper.get('[data-test="agent-state"]').attributes('data-state')).toBe('busy')
    idle.org.upsertAgent(makeAgent({ id: 2, slug: 'dev', name: 'Dev', reports_to: 1, enabled: false }))
    await flushPromises()
    expect(idle.wrapper.find('[data-test="agent-state"]').exists()).toBe(false)
  })

  it('a chave é um switch que liga e desliga pelo PATCH', async () => {
    const { wrapper, fetch, org } = await mountHeader({}, {
      'PATCH /api/agents/2': () => jsonResponse(makeAgent({ id: 2, slug: 'dev', name: 'Dev', reports_to: 1, enabled: false })),
    })
    const toggle = wrapper.get('[data-test="agent-toggle"]')
    expect(toggle.attributes('role')).toBe('switch')
    expect(toggle.attributes('aria-checked')).toBe('true')
    await toggle.trigger('click')
    await flushPromises()
    expect(bodyOf(fetch, 'PATCH', '/api/agents/2')).toEqual({ enabled: false })
    expect(org.byId(2)?.enabled).toBe(false)
    expect(wrapper.get('[data-test="agent-toggle"]').attributes('aria-checked')).toBe('false')
  })

  it('a chave que falha volta ao estado anterior e mostra o erro', async () => {
    const { wrapper, org } = await mountHeader({}, { 'PATCH /api/agents/2': () => jsonResponse({ detail: 'Não foi possível salvar.' }, 500) })
    await wrapper.get('[data-test="agent-toggle"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-test="agent-toggle"]').attributes('aria-checked')).toBe('true')
    expect(org.byId(2)?.enabled).toBe(true)
    expect(wrapper.get('[data-test="agent-error"]').attributes('role')).toBe('alert')
    expect(wrapper.get('[data-test="agent-error"]').text()).toContain('Não foi possível salvar.')
  })

  it('a chave já mostra o novo estado enquanto o pedido não volta', async () => {
    let release: (r: Response) => void = () => {}
    const { wrapper } = await mountHeader({}, { 'PATCH /api/agents/2': () => new Promise<Response>((resolve) => { release = resolve }) })
    await wrapper.get('[data-test="agent-toggle"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-test="agent-toggle"]').attributes('aria-checked')).toBe('false')
    expect(wrapper.get('[data-test="agent-toggle"]').attributes('disabled')).toBeDefined()
    release(jsonResponse({ detail: 'Falhou.' }, 500))
    await flushPromises()
    expect(wrapper.get('[data-test="agent-toggle"]').attributes('aria-checked')).toBe('true')
  })

  describe('rodar agora', () => {
    it('sem instrução não manda texto e avisa que está na fila', async () => {
      const { wrapper, fetch } = await mountHeader({}, { 'POST /api/agents/2/wake': () => jsonResponse({ id: 5 }, 202) })
      await wrapper.get('[data-test="agent-run"]').trigger('click')
      await flushPromises()
      expect(bodyOf(fetch, 'POST', '/api/agents/2/wake')).toEqual({})
      expect(wrapper.get('[data-test="agent-run-ok"]').text()).toBe('Pedido na fila: a execução começa assim que o agente puder.')
    })

    it('mostra o erro de rodar agora', async () => {
      const { wrapper } = await mountHeader({}, { 'POST /api/agents/2/wake': () => jsonResponse({ detail: 'A fila do agente está cheia.' }, 409) })
      await wrapper.get('[data-test="agent-run"]').trigger('click')
      await flushPromises()
      expect(wrapper.get('[data-test="agent-error"]').attributes('role')).toBe('alert')
      expect(wrapper.get('[data-test="agent-error"]').text()).toContain('A fila do agente está cheia.')
      expect(wrapper.find('[data-test="agent-run-ok"]').exists()).toBe(false)
    })

    it('com a definição inválida fica desabilitado e explica', async () => {
      const { wrapper } = await mountHeader({ definition_error: 'Falta o campo name.' })
      expect(wrapper.get('[data-test="agent-run"]').attributes('disabled')).toBeDefined()
      expect(wrapper.get('[data-test="agent-run-blocked"]').text()).toBe('A definição do agente está inválida: corrija o AGENT.md para poder rodar.')
      expect(wrapper.find('[data-test="agent-off"]').exists()).toBe(false)
    })

    it('"Rodar com instrução…" abre o diálogo e manda o texto', async () => {
      const { wrapper, fetch } = await mountHeader({}, { 'POST /api/agents/2/wake': () => jsonResponse({ id: 5 }, 202) })
      await choose(wrapper, 'run-with-text')
      await wrapper.get('[data-test="agent-run-text"]').setValue('Limpar o cache')
      await wrapper.get('[data-test="confirm-ok"]').trigger('click')
      await flushPromises()
      expect(bodyOf(fetch, 'POST', '/api/agents/2/wake')).toEqual({ text: 'Limpar o cache' })
      expect(wrapper.find('[data-test="agent-run-text"]').exists()).toBe(false)
      expect(wrapper.get('[data-test="agent-run-ok"]').text()).toContain('na fila')
    })

    it('se o pedido com instrução falha, o texto continua para uma nova tentativa', async () => {
      const { wrapper } = await mountHeader({}, { 'POST /api/agents/2/wake': () => jsonResponse({ detail: 'A fila do agente está cheia.' }, 409) })
      await choose(wrapper, 'run-with-text')
      await wrapper.get('[data-test="agent-run-text"]').setValue('Limpar o cache')
      await wrapper.get('[data-test="confirm-ok"]').trigger('click')
      await flushPromises()
      expect(wrapper.get('[data-test="agent-error"]').text()).toContain('A fila do agente está cheia.')
      await choose(wrapper, 'run-with-text')
      expect(wrapper.get<HTMLInputElement>('[data-test="agent-run-text"]').element.value).toBe('Limpar o cache')
    })

    it('com outra ação em andamento, o diálogo não deixa confirmar e não descarta o pedido', async () => {
      let release: (r: Response) => void = () => {}
      const { wrapper, fetch } = await mountHeader({}, {
        'PATCH /api/agents/2': () => new Promise<Response>((resolve) => { release = resolve }),
        'POST /api/agents/2/wake': () => jsonResponse({ id: 5 }, 202),
      })
      await wrapper.get('[data-test="agent-toggle"]').trigger('click') // salvando: a tela fica ocupada
      await choose(wrapper, 'run-with-text')
      await wrapper.get('[data-test="agent-run-text"]').setValue('Limpar o cache')
      expect(wrapper.get('[data-test="confirm-ok"]').attributes('disabled')).toBeDefined()
      await wrapper.get('form').trigger('submit') // Enter no campo
      await flushPromises()
      expect(wrapper.find('[data-test="agent-run-text"]').exists()).toBe(true)
      expect(fetch.mock.calls.some(([u]) => u === '/api/agents/2/wake')).toBe(false)
      release(jsonResponse(makeAgent({ id: 2, slug: 'dev', name: 'Dev', reports_to: 1 })))
      await flushPromises()
      expect(wrapper.get('[data-test="confirm-ok"]').attributes('disabled')).toBeUndefined()
      await wrapper.get('[data-test="confirm-ok"]').trigger('click')
      await flushPromises()
      expect(bodyOf(fetch, 'POST', '/api/agents/2/wake')).toEqual({ text: 'Limpar o cache' })
    })

    it('cancelar o diálogo não pede nada', async () => {
      const { wrapper, fetch } = await mountHeader()
      fetch.mockClear()
      await choose(wrapper, 'run-with-text')
      await wrapper.get('[data-test="confirm-cancel"]').trigger('click')
      expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
      expect(fetch).not.toHaveBeenCalled()
    })
  })

  describe('menu Mais ações', () => {
    it('tem os quatro itens, o de excluir como perigo', async () => {
      const { wrapper } = await mountHeader()
      await wrapper.get('[data-test="agent-more"]').trigger('click')
      await flushPromises()
      const items = Array.from(document.body.querySelectorAll<HTMLElement>('[data-test="more-menu-item"]'))
      expect(items.map((i) => [i.dataset.id, i.textContent])).toEqual([
        ['run-with-text', 'Rodar com instrução…'],
        ['boss', 'Trocar chefe…'],
        ['duplicate', 'Duplicar para outro projeto…'],
        ['delete', 'Excluir…'],
      ])
      expect(items[3]!.className).toContain('text-diff-del-fg')
    })

    it('"Trocar chefe…" lista os outros agentes do projeto e salva', async () => {
      const { wrapper, fetch, org } = await mountHeader({}, {
        'PATCH /api/agents/2': () => jsonResponse(makeAgent({ id: 2, slug: 'dev', name: 'Dev', reports_to: 10 })),
      })
      org.agents = [...org.agents, makeAgent({ id: 10, slug: 'novo', name: 'Novo chefe' })]
      await choose(wrapper, 'boss')
      expect(wrapper.findAll('[data-test="agent-boss"] option').map((o) => o.text())).toEqual(['Ninguém (topo)', 'Maestro', 'Novo chefe', 'Revisor'])
      expect(wrapper.get<HTMLSelectElement>('[data-test="agent-boss"]').element.value).toBe('1')
      await wrapper.get('[data-test="agent-boss"]').setValue('10')
      await wrapper.get('[data-test="confirm-ok"]').trigger('click')
      await flushPromises()
      expect(bodyOf(fetch, 'PATCH', '/api/agents/2')).toEqual({ reports_to: 10 })
      expect(org.byId(2)?.reports_to).toBe(10)
      expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    })

    it('tirar o chefe manda reports_to nulo', async () => {
      const { wrapper, fetch } = await mountHeader({}, {
        'PATCH /api/agents/2': () => jsonResponse(makeAgent({ id: 2, slug: 'dev', name: 'Dev', reports_to: null })),
      })
      await choose(wrapper, 'boss')
      await wrapper.get('[data-test="agent-boss"]').setValue('')
      await wrapper.get('[data-test="confirm-ok"]').trigger('click')
      await flushPromises()
      expect(bodyOf(fetch, 'PATCH', '/api/agents/2')).toEqual({ reports_to: null })
    })

    it('trocar chefe mostra o 422 e o agente continua com o chefe de antes', async () => {
      const { wrapper, org } = await mountHeader({}, { 'PATCH /api/agents/2': () => jsonResponse({ detail: 'Isso criaria um ciclo na organização.' }, 422) })
      await choose(wrapper, 'boss')
      await wrapper.get('[data-test="agent-boss"]').setValue('3')
      await wrapper.get('[data-test="confirm-ok"]').trigger('click')
      await flushPromises()
      expect(wrapper.get('[data-test="agent-error"]').text()).toContain('ciclo')
      expect(wrapper.get('[data-test="agent-error"]').attributes('role')).toBe('alert')
      expect(org.byId(2)?.reports_to).toBe(1)
      await choose(wrapper, 'boss')
      expect(wrapper.get<HTMLSelectElement>('[data-test="agent-boss"]').element.value).toBe('1')
    })

    it('duplica para outro projeto e abre a cópia na definição', async () => {
      const copy = makeAgent({ id: 10, slug: 'dev', name: 'Dev', project_id: 9 })
      const { wrapper, fetch, router, org } = await mountHeader({}, { 'POST /api/agents/2/duplicate': () => jsonResponse(copy, 201) })
      await choose(wrapper, 'duplicate')
      expect(wrapper.get<HTMLInputElement>('[data-test="duplicate-slug"]').element.value).toBe('dev')
      await wrapper.get('[data-test="duplicate-project"]').setValue('9')
      await wrapper.get('[data-test="confirm-ok"]').trigger('click')
      await flushPromises()
      expect(bodyOf(fetch, 'POST', '/api/agents/2/duplicate')).toEqual({ project_id: 9, slug: 'dev' })
      expect(org.byId(10)?.project_id).toBe(9)
      expect(router.currentRoute.value.fullPath).toBe('/agentes/9?agente=10&aba=definicao')
      expect(wrapper.find('[data-test="duplicate-slug"]').exists()).toBe(false)
    })

    it('o diálogo de duplicar não oferece o embutido "Sem projeto"', async () => {
      const { wrapper } = await mountHeader()
      await choose(wrapper, 'duplicate')
      expect(wrapper.get('[data-test="duplicate-project"]').findAll('option').map((o) => o.text())).toEqual(['Loja', 'Blog'])
    })

    it('duplicar mostra o erro dentro do diálogo e mantém o diálogo aberto', async () => {
      const { wrapper } = await mountHeader({}, { 'POST /api/agents/2/duplicate': () => jsonResponse({ detail: 'Já existe um agente com esse identificador.' }, 409) })
      await choose(wrapper, 'duplicate')
      await wrapper.get('[data-test="confirm-ok"]').trigger('click')
      await flushPromises()
      expect(wrapper.get('[data-test="duplicate-error"]').attributes('role')).toBe('alert')
      expect(wrapper.get('[data-test="duplicate-error"]').text()).toContain('Já existe')
      expect(wrapper.find('[data-test="duplicate-slug"]').exists()).toBe(true)
    })

    it('duplicar com identificador inválido não envia', async () => {
      const { wrapper } = await mountHeader()
      await choose(wrapper, 'duplicate')
      await wrapper.get('[data-test="duplicate-slug"]').setValue('Nome Ruim')
      expect(wrapper.get('[data-test="confirm-ok"]').attributes('disabled')).toBeDefined()
    })

    it('excluir pede confirmação, apaga e avisa o painel', async () => {
      const { wrapper, fetch, org } = await mountHeader({}, { 'DELETE /api/agents/2': () => jsonResponse(undefined, 204) })
      await choose(wrapper, 'delete')
      expect(wrapper.get('[role="dialog"]').text()).toContain('Dev')
      expect(fetch.mock.calls.some(([, init]) => init?.method === 'DELETE')).toBe(false)
      await wrapper.get('[data-test="confirm-ok"]').trigger('click')
      await flushPromises()
      expect(fetch.mock.calls.some(([u, init]) => u === '/api/agents/2' && init?.method === 'DELETE')).toBe(true)
      expect(wrapper.emitted('deleted')).toHaveLength(1)
      expect(org.byId(2)).toBeUndefined()
    })

    it('cancelar a confirmação não apaga', async () => {
      const { wrapper, fetch } = await mountHeader()
      fetch.mockClear()
      await choose(wrapper, 'delete')
      await wrapper.get('[data-test="confirm-cancel"]').trigger('click')
      expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
      expect(fetch).not.toHaveBeenCalled()
    })

    it('excluir um agente ocupado mostra o motivo e continua listado', async () => {
      const { wrapper, org } = await mountHeader({}, { 'DELETE /api/agents/2': () => jsonResponse({ detail: 'O agente está executando.' }, 409) })
      await choose(wrapper, 'delete')
      await wrapper.get('[data-test="confirm-ok"]').trigger('click')
      await flushPromises()
      expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
      expect(wrapper.get('[data-test="agent-error"]').text()).toContain('O agente está executando.')
      expect(wrapper.emitted('deleted')).toBeUndefined()
      expect(org.byId(2)).toBeDefined()
    })
  })

  describe('agente desligado', () => {
    it('com uma rotina ligada avisa da próxima e bloqueia o rodar agora', async () => {
      const { wrapper } = await mountHeader({ enabled: false }, {}, [makeRoutine({ id: 1, agent_id: 2, enabled: true, schedules: EVERY_DAY_1840 })])
      expect(wrapper.get('[data-test="agent-run"]').attributes('disabled')).toBeDefined()
      expect(wrapper.get('[data-test="agent-off"]').text()).toBe('Agente desligado. A rotina continua agendada, mas a próxima (hoje 18:40) não roda enquanto ele estiver assim.')
      expect(wrapper.get('[data-test="agent-toggle"]').attributes('aria-checked')).toBe('false')
    })

    it('com duas rotinas ligadas fala no plural', async () => {
      const { wrapper } = await mountHeader({ enabled: false }, {}, [
        makeRoutine({ id: 1, agent_id: 2, enabled: true, schedules: EVERY_DAY_1840 }),
        makeRoutine({ id: 2, agent_id: 2, enabled: true, schedules: [{ id: 2, days: '12345', time: '09:00', last_fired_at: null }] }),
      ])
      expect(wrapper.get('[data-test="agent-off"]').text()).toBe('Agente desligado. As 2 rotinas continuam agendadas, mas a próxima (hoje 18:40) não roda enquanto ele estiver assim.')
    })

    it('ignora rotinas desligadas e de outros agentes', async () => {
      const { wrapper } = await mountHeader({ enabled: false }, {}, [
        makeRoutine({ id: 1, agent_id: 2, enabled: false, schedules: EVERY_DAY_1840 }),
        makeRoutine({ id: 2, agent_id: 3, enabled: true, schedules: EVERY_DAY_1840 }),
      ])
      expect(wrapper.get('[data-test="agent-off"]').text()).toBe('Agente desligado. Nada roda enquanto ele estiver assim.')
    })

    it('sem rotina ligada diz que nada roda', async () => {
      const { wrapper } = await mountHeader({ enabled: false })
      expect(wrapper.get('[data-test="agent-off"]').text()).toBe('Agente desligado. Nada roda enquanto ele estiver assim.')
    })

    it('rotina ligada sem horário não conta como agendada', async () => {
      const { wrapper } = await mountHeader({ enabled: false }, {}, [makeRoutine({ id: 1, agent_id: 2, enabled: true, schedules: [] })])
      expect(wrapper.get('[data-test="agent-off"]').text()).toBe('Agente desligado. Nada roda enquanto ele estiver assim.')
    })

    it('se a leitura das rotinas falha, só diz que está desligado, sem afirmar que nada roda', async () => {
      const { wrapper } = await mountHeader({ enabled: false }, { 'GET /api/routines?project_id=1': () => jsonResponse({ detail: 'erro' }, 500) })
      expect(wrapper.get('[data-test="agent-off"]').text()).toBe('Agente desligado.')
      expect(wrapper.get('[data-test="agent-off-enable"]').text()).toBe('Ligar agente')
    })

    it('enquanto as rotinas carregam, só diz que está desligado e depois completa a frase', async () => {
      let release: (r: Response) => void = () => {}
      const { wrapper } = await mountHeader({ enabled: false }, { 'GET /api/routines?project_id=1': () => new Promise<Response>((resolve) => { release = resolve }) })
      expect(wrapper.get('[data-test="agent-off"]').text()).toBe('Agente desligado.')
      expect(wrapper.find('[data-test="agent-off-enable"]').exists()).toBe(true)
      release(jsonResponse([makeRoutine({ id: 1, agent_id: 2, enabled: true, schedules: EVERY_DAY_1840 })]))
      await flushPromises()
      expect(wrapper.get('[data-test="agent-off"]').text()).toBe('Agente desligado. A rotina continua agendada, mas a próxima (hoje 18:40) não roda enquanto ele estiver assim.')
    })

    it('"Ligar agente" liga pelo PATCH', async () => {
      const { wrapper, fetch, org } = await mountHeader({ enabled: false }, {
        'PATCH /api/agents/2': () => jsonResponse(makeAgent({ id: 2, slug: 'dev', name: 'Dev', reports_to: 1, enabled: true })),
      })
      const enable = wrapper.get('[data-test="agent-off-enable"]')
      expect(enable.text()).toBe('Ligar agente')
      await enable.trigger('click')
      await flushPromises()
      expect(bodyOf(fetch, 'PATCH', '/api/agents/2')).toEqual({ enabled: true })
      expect(org.byId(2)?.enabled).toBe(true)
      expect(wrapper.find('[data-test="agent-off"]').exists()).toBe(false)
      expect(wrapper.get('[data-test="agent-run"]').attributes('disabled')).toBeUndefined()
    })

    it('ligado não mostra o aviso', async () => {
      const { wrapper } = await mountHeader()
      expect(wrapper.find('[data-test="agent-off"]').exists()).toBe(false)
      expect(wrapper.find('[data-test="agent-off-enable"]').exists()).toBe(false)
    })

    it('"Rodar com instrução…" fica desabilitado com o agente desligado', async () => {
      const { wrapper } = await mountHeader({ enabled: false })
      await wrapper.get('[data-test="agent-more"]').trigger('click')
      await flushPromises()
      expect(menuItem('run-with-text')!.getAttribute('aria-disabled')).toBe('true')
      expect(menuItem('boss')!.getAttribute('aria-disabled')).toBeNull()
    })
  })
})
