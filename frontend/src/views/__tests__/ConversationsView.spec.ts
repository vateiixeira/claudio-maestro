import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import ConversationsView from '../ConversationsView.vue'
import { createAppRouter } from '../../router'
import { useGroupsStore } from '../../stores/groups'
import { useNewConversationStore } from '../../stores/newConversation'
import { useProjectsStore } from '../../stores/projects'
import { useSessionsStore } from '../../stores/sessions'
import { jsonResponse, makeGroup, makeProject, makeSession, routeFetch } from '../../test/factories'

vi.mock('../../stores/realtime', () => ({ loadEverything: vi.fn(() => Promise.resolve()) }))
import { loadEverything } from '../../stores/realtime'

enableAutoUnmount(afterEach)
let pinia: Pinia
const now = Date.now() / 1000

beforeEach(() => {
  vi.mocked(loadEverything).mockClear()
  pinia = createPinia()
  setActivePinia(pinia)
  const projects = useProjectsStore(pinia)
  projects.projects = [makeProject({ id: 1, name: 'a' }), makeProject({ id: 2, name: 'b', path: '/b' })]
  projects.loaded = true
  useSessionsStore(pinia).loaded = true
  vi.stubGlobal('fetch', routeFetch({
    'GET /api/projects/1/git': () => jsonResponse({ repos: [] }),
    'GET /api/projects/2/git': () => jsonResponse({ repos: [] }),
  }))
})
afterEach(() => vi.unstubAllGlobals())

async function mountList(path = '/sessions') {
  const router = createAppRouter(createMemoryHistory())
  await router.push(path)
  const wrapper = mount(ConversationsView, { global: { plugins: [pinia, router] } })
  await flushPromises()
  return { wrapper, router }
}

describe('Conversas', () => {
  it('lista todas por última atividade, com grupos de data', async () => {
    useSessionsStore(pinia).setForProject(1, [
      makeSession({ session_id: 'a', title: 'Hoje', last_activity_at: now }),
      makeSession({ session_id: 'b', title: 'Semana', last_activity_at: now - 3 * 86400, display_state: 'finished' }),
      makeSession({ session_id: 'c', title: 'Velha', last_activity_at: now - 30 * 86400 }),
    ])
    const { wrapper } = await mountList()

    expect(wrapper.findAll('[data-test="row-link"]').map((r) => r.text())).toEqual(['Hoje', 'Semana', 'Velha'])
    expect(wrapper.findAll('[data-test="date-group"]').map((g) => g.text())).toEqual(['Hoje', 'Esta semana', 'Antes'])
  })

  it('filtra por estado e projeto, guardando na URL', async () => {
    useSessionsStore(pinia).setForProject(1, [makeSession({ session_id: 'a', title: 'Aberta', last_activity_at: now })])
    useSessionsStore(pinia).setForProject(2, [makeSession({ session_id: 'b', project_id: 2, title: 'Feita', display_state: 'finished', last_activity_at: now })])
    const { wrapper, router } = await mountList('/sessions?estado=finalizadas')

    expect(wrapper.findAll('[data-test="row-link"]').map((r) => r.text())).toEqual(['Feita'])
    await wrapper.find('[data-test="conversations-state"]').setValue('todas')
    await wrapper.find('[data-test="conversations-project"]').setValue('1')
    await flushPromises()
    expect(router.currentRoute.value.query).toMatchObject({ estado: 'todas', projeto: '1' })
    expect(wrapper.findAll('[data-test="row-link"]').map((r) => r.text())).toEqual(['Aberta'])
  })

  it('mostra 100 por vez', async () => {
    useSessionsStore(pinia).setForProject(1, Array.from({ length: 150 }, (_, i) =>
      makeSession({ session_id: `s${i}`, title: `T${i}`, last_activity_at: now - i }),
    ))
    const { wrapper } = await mountList()

    expect(wrapper.findAll('[data-test="conversation-row"]')).toHaveLength(100)
    await wrapper.find('[data-test="show-more"]').trigger('click')
    expect(wrapper.findAll('[data-test="conversation-row"]')).toHaveLength(150)
    expect(wrapper.find('[data-test="show-more"]').exists()).toBe(false)
  })

  it('"Nova conversa" abre o modal com o projeto filtrado', async () => {
    const { wrapper } = await mountList('/sessions?projeto=2')
    await wrapper.find('[data-test="conversations-new"]').trigger('click')
    const store = useNewConversationStore(pinia)
    expect(store.isOpen).toBe(true)
    expect(store.presetProjectId).toBe(2)
  })

  it('duas mudanças de filtro seguidas chegam as duas à URL', async () => {
    const { wrapper, router } = await mountList()
    await wrapper.find('[data-test="conversations-state"]').setValue('ativas')
    await wrapper.find('[data-test="conversations-project"]').setValue('2')
    await flushPromises()
    expect(router.currentRoute.value.query).toMatchObject({ estado: 'ativas', projeto: '2' })
  })

  it('filtra pelo título com ?busca=', async () => {
    useSessionsStore(pinia).setForProject(1, [
      makeSession({ session_id: 'a', title: 'Corrigir login', last_activity_at: now }),
      makeSession({ session_id: 'b', title: 'Ajustar tabela', last_activity_at: now - 1 }),
    ])
    const { wrapper } = await mountList('/sessions?busca=LOGIN')
    expect(wrapper.findAll('[data-test="row-link"]').map((r) => r.text())).toEqual(['Corrigir login'])
  })

  it('continua aplicando filtros depois de uma navegação que falhou', async () => {
    const { wrapper, router } = await mountList()
    const spy = vi.spyOn(router, 'replace').mockRejectedValueOnce(new Error('guarda'))
    await wrapper.find('[data-test="conversations-state"]').setValue('ativas')
    await flushPromises()
    await wrapper.find('[data-test="conversations-project"]').setValue('2')
    await flushPromises()
    expect(spy).toHaveBeenCalledTimes(2)
    expect(router.currentRoute.value.query).toMatchObject({ projeto: '2' })
    spy.mockRestore()
  })

  it('enquanto as conversas carregam mostra "Carregando…" e não o aviso de vazio', async () => {
    useSessionsStore(pinia).loaded = false
    const { wrapper } = await mountList()
    expect(wrapper.find('[data-test="load-loading"]').text()).toBe('Carregando…')
    expect(wrapper.find('[data-test="empty"]').exists()).toBe(false)
  })

  it('se os projetos falharam mostra o erro com "Tentar de novo"', async () => {
    useSessionsStore(pinia).loaded = false
    useProjectsStore(pinia).loadError = 'Servidor caiu.'
    const { wrapper } = await mountList()
    expect(wrapper.find('[data-test="load-error"]').text()).toContain('Servidor caiu.')
    expect(wrapper.find('[data-test="empty"]').exists()).toBe(false)
    await wrapper.find('[data-test="load-retry"]').trigger('click')
    expect(loadEverything).toHaveBeenCalledTimes(1)
  })

  describe('agrupador', () => {
    const titles = (wrapper: Awaited<ReturnType<typeof mountList>>['wrapper']) =>
      wrapper.findAll('[data-test="row-link"]').map((r) => r.text())

    function seedGroups() {
      useGroupsStore(pinia).groups = [makeGroup({ id: 1, name: 'A' }), makeGroup({ id: 2, name: 'B' })]
      useSessionsStore(pinia).setForProject(1, [
        makeSession({ session_id: 'a', title: 'Em A', group_id: 1, last_activity_at: now }),
        makeSession({ session_id: 'b', title: 'Em B', group_id: 2, last_activity_at: now - 1 }),
        makeSession({ session_id: 'c', title: 'Solta', group_id: null, last_activity_at: now - 2 }),
      ])
    }

    it('sem projeto escolhido não mostra o filtro de agrupador', async () => {
      seedGroups()
      const { wrapper } = await mountList()
      expect(wrapper.find('[data-test="conversations-group"]').exists()).toBe(false)
    })

    it('lista "Todos", "Sem agrupador" e os agrupadores do projeto', async () => {
      seedGroups()
      const { wrapper } = await mountList('/sessions?projeto=1')
      const options = wrapper.findAll('[data-test="conversations-group"] option').map((o) => o.text())
      expect(options).toEqual(['Todos os agrupadores', 'Sem agrupador', 'A', 'B'])
    })

    it('não mostra o filtro quando o projeto não tem agrupadores', async () => {
      seedGroups()
      const { wrapper } = await mountList('/sessions?projeto=2')
      expect(wrapper.find('[data-test="conversations-group"]').exists()).toBe(false)
    })

    it('filtra por um agrupador e pelas sessões sem agrupador', async () => {
      seedGroups()
      const one = await mountList('/sessions?projeto=1&agrupador=1')
      expect(titles(one.wrapper)).toEqual(['Em A'])
      const loose = await mountList('/sessions?projeto=1&agrupador=sem')
      expect(titles(loose.wrapper)).toEqual(['Solta'])
    })

    it('escolher no select guarda o agrupador na URL', async () => {
      seedGroups()
      const { wrapper, router } = await mountList('/sessions?projeto=1')
      await wrapper.find('[data-test="conversations-group"]').setValue('2')
      await flushPromises()
      expect(router.currentRoute.value.query.agrupador).toBe('2')
      expect(titles(wrapper)).toEqual(['Em B'])
    })

    it('ignora um agrupador que não é do projeto escolhido', async () => {
      seedGroups()
      useGroupsStore(pinia).groups.push(makeGroup({ id: 3, project_id: 2, name: 'C' }))
      const { wrapper } = await mountList('/sessions?projeto=1&agrupador=3')
      expect(titles(wrapper)).toEqual(['Em A', 'Em B', 'Solta'])
      expect((wrapper.find('[data-test="conversations-group"]').element as HTMLSelectElement).value).toBe('')
    })

    it('trocar o projeto limpa o agrupador da URL', async () => {
      seedGroups()
      const { wrapper, router } = await mountList('/sessions?projeto=1&agrupador=1&estado=ativas')
      await wrapper.find('[data-test="conversations-project"]').setValue('2')
      await flushPromises()
      expect(router.currentRoute.value.query).toEqual({ projeto: '2', estado: 'ativas' })
    })

    it('a busca também encontra pelo nome do agrupador', async () => {
      useGroupsStore(pinia).groups = [makeGroup({ id: 1, name: 'Checkout' })]
      useSessionsStore(pinia).setForProject(1, [
        makeSession({ session_id: 'a', title: 'Ajustar botão', group_id: 1, last_activity_at: now }),
        makeSession({ session_id: 'b', title: 'Outra coisa', group_id: null, last_activity_at: now - 1 }),
      ])
      const { wrapper } = await mountList('/sessions?busca=checkout')
      expect(titles(wrapper)).toEqual(['Ajustar botão'])
    })
  })
})
