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

const chip = (wrapper: { find: (sel: string) => any }, state: string) => wrapper.find(`[data-test="conversations-chip"][data-state="${state}"]`)

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
    await chip(wrapper, 'todas').trigger('click')
    await wrapper.find('[data-test="conversations-project"]').setValue('1')
    await flushPromises()
    expect(router.currentRoute.value.query).toEqual({ projeto: '1' })
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

    it('o filtro inclui o agrupador de outro projeto que tem conversa do projeto escolhido', async () => {
      useGroupsStore(pinia).groups = [makeGroup({ id: 1, project_id: 1, name: 'A' }), makeGroup({ id: 9, project_id: 2, name: 'Compartilhado' })]
      useSessionsStore(pinia).setForProject(1, [
        makeSession({ session_id: 'a', title: 'Em A', group_id: 1, last_activity_at: now }),
        makeSession({ session_id: 'x', title: 'No compartilhado', group_id: 9, last_activity_at: now - 1 }),
      ])
      const { wrapper } = await mountList('/sessions?projeto=1&agrupador=9')
      expect(wrapper.findAll('[data-test="conversations-group"] option').map((o) => o.text())).toEqual(['Todos os agrupadores', 'Sem agrupador', 'A', 'Compartilhado'])
      expect(titles(wrapper)).toEqual(['No compartilhado'])
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

describe('filtros de marcação', () => {
  beforeEach(() => {
    useSessionsStore(pinia).setForProject(1, [
      makeSession({ session_id: 'e', title: 'Espera', mark: 'on_hold', last_activity_at: now }),
      makeSession({ session_id: 'b', title: 'Bloq', mark: 'blocked', last_activity_at: now - 1 }),
      makeSession({ session_id: 'r', title: 'Rev', mark: 'review', priority: true, last_activity_at: now - 2 }),
      makeSession({ session_id: 'n', title: 'Nada', last_activity_at: now - 3 }),
    ])
  })
  const titles = (w: Awaited<ReturnType<typeof mountList>>['wrapper']) => w.findAll('[data-test="row-link"]').map((r) => r.text())

  it.each([
    ['em-espera', ['Espera']],
    ['bloqueadas', ['Bloq']],
    ['para-revisar', ['Rev']],
    ['prioridade', ['Rev']],
  ])('?estado=%s mostra só as marcadas assim', async (estado, expected) => {
    const { wrapper } = await mountList(`/sessions?estado=${estado}`)
    expect(titles(wrapper)).toEqual(expected)
  })
})

describe('Conversas: sessões descartadas', () => {
  const titles = (wrapper: { findAll: (sel: string) => { text: () => string }[] }) => wrapper.findAll('[data-test="row-link"]').map((r) => r.text())

  it('ficam fora de Todas, Ativas e Finalizadas', async () => {
    useSessionsStore(pinia).setForProject(1, [
      makeSession({ session_id: 'a', title: 'Aberta', last_activity_at: now }),
      makeSession({ session_id: 'fim', title: 'Feita', display_state: 'finished', last_activity_at: now }),
      makeSession({ session_id: 'desc', title: 'Descartada', mark: 'discarded', last_activity_at: now }),
      makeSession({ session_id: 'descfim', title: 'Descartada feita', mark: 'discarded', display_state: 'finished', last_activity_at: now }),
    ])
    expect(titles((await mountList('/sessions')).wrapper).sort()).toEqual(['Aberta', 'Feita'])
    expect(titles((await mountList('/sessions?estado=ativas')).wrapper)).toEqual(['Aberta'])
    expect(titles((await mountList('/sessions?estado=finalizadas')).wrapper)).toEqual(['Feita'])
  })

  it('a aba Descartadas lista só as descartadas, abertas ou não', async () => {
    useSessionsStore(pinia).setForProject(1, [
      makeSession({ session_id: 'a', title: 'Aberta', last_activity_at: now }),
      makeSession({ session_id: 'desc', title: 'Descartada', mark: 'discarded', last_activity_at: now }),
      makeSession({ session_id: 'descfim', title: 'Descartada feita', mark: 'discarded', display_state: 'finished', last_activity_at: now }),
    ])
    const { wrapper } = await mountList('/sessions?estado=descartadas')
    expect(titles(wrapper).sort()).toEqual(['Descartada', 'Descartada feita'])
  })
})

describe('Conversas: Descartar ao lado de Finalizar', () => {
  it('cada conversa aberta tem Descartar logo antes de Finalizar', async () => {
    useSessionsStore(pinia).setForProject(1, [makeSession({ session_id: 'a', title: 'Aberta', last_activity_at: now })])
    const { wrapper } = await mountList('/sessions')
    const discard = wrapper.get('[data-test="row-discard"]')
    expect(discard.text()).toBe('Descartar')
    expect(discard.attributes('aria-label')).toBe('Descartar Aberta')
    expect(discard.element.nextElementSibling?.getAttribute('data-test')).toBe('row-finish')
  })

  it('clicar em Descartar marca a conversa como descartada', async () => {
    useSessionsStore(pinia).setForProject(1, [makeSession({ session_id: 'a', title: 'Aberta', last_activity_at: now })])
    const spy = vi.spyOn(useSessionsStore(pinia), 'setMark').mockResolvedValue()
    const { wrapper } = await mountList('/sessions')
    await wrapper.get('[data-test="row-discard"]').trigger('click')
    expect(spy).toHaveBeenCalledWith('a', 'discarded')
  })

  it('falha ao descartar aparece como erro da lista', async () => {
    useSessionsStore(pinia).setForProject(1, [makeSession({ session_id: 'a', title: 'Aberta', last_activity_at: now })])
    vi.spyOn(useSessionsStore(pinia), 'setMark').mockRejectedValue(new Error('Falhou aqui'))
    const { wrapper } = await mountList('/sessions')
    await wrapper.get('[data-test="row-discard"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('Falhou aqui')
  })

  it('na aba Descartadas a conversa não oferece Descartar de novo', async () => {
    useSessionsStore(pinia).setForProject(1, [makeSession({ session_id: 'd', title: 'Descartada', mark: 'discarded', last_activity_at: now })])
    const { wrapper } = await mountList('/sessions?estado=descartadas')
    expect(wrapper.findAll('[data-test="row-link"]')).toHaveLength(1)
    expect(wrapper.find('[data-test="row-discard"]').exists()).toBe(false)
  })
})

describe('Conversas: chips de estado', () => {
  const chips = (w: Awaited<ReturnType<typeof mountList>>['wrapper']) => w.findAll('[data-test="conversations-chip"]')
  const titles = (w: Awaited<ReturnType<typeof mountList>>['wrapper']) => w.findAll('[data-test="row-link"]').map((r) => r.text())

  beforeEach(() => {
    useSessionsStore(pinia).setForProject(1, [
      makeSession({ session_id: 'run', title: 'Rodando', display_state: 'running', last_activity_at: now }),
      makeSession({ session_id: 'run2', title: 'Rodando também', display_state: 'running', unread: true, last_activity_at: now - 1 }),
      makeSession({ session_id: 'turn', title: 'Sua vez aqui', display_state: 'waiting', state: 'idle', last_activity_at: now - 2 }),
      makeSession({ session_id: 'hold', title: 'Parada', display_state: 'waiting', state: 'idle', mark: 'on_hold', last_activity_at: now - 3 }),
      makeSession({ session_id: 'fin', title: 'Feita', display_state: 'finished', unread: true, last_activity_at: now - 4 }),
      makeSession({ session_id: 'disc', title: 'Jogada fora', display_state: 'running', mark: 'discarded', last_activity_at: now - 5 }),
    ])
    useSessionsStore(pinia).setForProject(2, [
      makeSession({ session_id: 'other', project_id: 2, title: 'Do outro', display_state: 'running', last_activity_at: now - 6 }),
    ])
  })

  it('são cinco, na ordem, com contagem nos três primeiros que contam', async () => {
    const { wrapper } = await mountList()
    expect(chips(wrapper).map((c) => c.attributes('data-state'))).toEqual(['todas', 'em-execucao', 'sua-vez', 'nao-lidas', 'finalizadas'])
    const text = (state: string) => chip(wrapper, state).text()
    expect(text('todas')).toBe('Todas')
    expect(text('em-execucao')).toBe('Em execução3')
    expect(text('sua-vez')).toBe('Sua vez1')
    expect(text('nao-lidas')).toBe('Não lidas1')
    expect(text('finalizadas')).toBe('Finalizadas')
    expect(chip(wrapper, 'finalizadas').find('[data-test="filter-chip-count"]').exists()).toBe(false)
  })

  it('o chip "Em execução" com contagem zero tem o ícone parado e apagado', async () => {
    useSessionsStore(pinia).setForProject(1, [makeSession({ session_id: 'f', display_state: 'finished', last_activity_at: now })])
    useSessionsStore(pinia).setForProject(2, [])
    const { wrapper } = await mountList()
    const icon = chip(wrapper, 'em-execucao').get('[data-shape="spinner"]')
    expect(icon.attributes('data-quiet')).toBe('true')
    expect(icon.get('svg').classes()).not.toContain('motion-safe:animate-spin')
  })

  it('o chip "Em execução" com sessões rodando gira e fica verde', async () => {
    const { wrapper } = await mountList()
    const icon = chip(wrapper, 'em-execucao').get('[data-shape="spinner"]')
    expect(icon.attributes('data-quiet')).toBeUndefined()
    expect(icon.get('svg').classes()).toContain('stroke-primary')
  })

  it('clicar num chip guarda o estado na URL e filtra; Todas tira o estado', async () => {
    const { wrapper, router } = await mountList()
    await chip(wrapper, 'em-execucao').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.query.estado).toBe('em-execucao')
    expect(titles(wrapper)).toEqual(['Rodando', 'Rodando também', 'Do outro'])
    expect(chip(wrapper, 'em-execucao').attributes('aria-pressed')).toBe('true')
    expect(chip(wrapper, 'todas').attributes('aria-pressed')).toBe('false')
    await chip(wrapper, 'todas').trigger('click')
    await flushPromises()
    expect('estado' in router.currentRoute.value.query).toBe(false)
    expect(chip(wrapper, 'todas').attributes('aria-pressed')).toBe('true')
  })

  it.each([
    ['sua-vez', ['Sua vez aqui']],
    ['nao-lidas', ['Rodando também']],
    ['finalizadas', ['Feita']],
  ])('?estado=%s lista só as conversas desse estado', async (estado, expected) => {
    const { wrapper } = await mountList(`/sessions?estado=${estado}&projeto=1`)
    expect(titles(wrapper)).toEqual(expected)
    expect(chip(wrapper, estado).attributes('aria-pressed')).toBe('true')
  })

  it('as contagens respeitam o projeto e o agrupador, não a busca nem o estado', async () => {
    const { wrapper } = await mountList('/sessions?projeto=1&busca=zzz&estado=finalizadas')
    expect(chip(wrapper, 'em-execucao').text()).toBe('Em execução2')
    expect(chip(wrapper, 'sua-vez').text()).toBe('Sua vez1')
    expect(chip(wrapper, 'nao-lidas').text()).toBe('Não lidas1')
  })

  it('as contagens respeitam o agrupador', async () => {
    useGroupsStore(pinia).groups = [makeGroup({ id: 1, name: 'A' })]
    useSessionsStore(pinia).setForProject(1, [
      makeSession({ session_id: 'a', group_id: 1, display_state: 'running', last_activity_at: now }),
      makeSession({ session_id: 'b', group_id: null, display_state: 'running', last_activity_at: now - 1 }),
    ])
    const { wrapper } = await mountList('/sessions?projeto=1&agrupador=1')
    expect(chip(wrapper, 'em-execucao').text()).toBe('Em execução1')
  })
})

describe('Conversas: Mais filtros', () => {
  const select = (w: Awaited<ReturnType<typeof mountList>>['wrapper']) => w.find('[data-test="conversations-state"]')

  it('tem "Mais filtros" e os estados que não são chips', async () => {
    const { wrapper } = await mountList()
    expect(select(wrapper).findAll('option').map((o) => o.text())).toEqual(['Mais filtros', 'Ativas', 'Em espera', 'Bloqueadas', 'Para revisar', 'Prioridade', 'Descartadas'])
    expect((select(wrapper).element as HTMLSelectElement).value).toBe('')
  })

  it('com um chip ligado continua em "Mais filtros"', async () => {
    const { wrapper } = await mountList('/sessions?estado=sua-vez')
    expect((select(wrapper).element as HTMLSelectElement).value).toBe('')
  })

  it('o endereço antigo ?estado=para-revisar continua filtrando e aparece no select', async () => {
    useSessionsStore(pinia).setForProject(1, [
      makeSession({ session_id: 'a', title: 'Rev', mark: 'review', last_activity_at: now }),
      makeSession({ session_id: 'b', title: 'Nada', last_activity_at: now - 1 }),
    ])
    const { wrapper } = await mountList('/sessions?estado=para-revisar')
    expect(wrapper.findAll('[data-test="row-link"]').map((r) => r.text())).toEqual(['Rev'])
    expect((select(wrapper).element as HTMLSelectElement).value).toBe('para-revisar')
    expect(select(wrapper).findAll('option').find((o) => (o.element as HTMLOptionElement).selected)?.text()).toBe('Para revisar')
    expect(wrapper.findAll('[data-test="conversations-chip"][aria-pressed="true"]')).toHaveLength(0)
  })

  it('voltar para "Mais filtros" tira o estado da URL', async () => {
    const { wrapper, router } = await mountList('/sessions?estado=ativas')
    await select(wrapper).setValue('')
    await flushPromises()
    expect('estado' in router.currentRoute.value.query).toBe(false)
  })
})

describe('Conversas: colunas e cabeçalho', () => {
  it('cada grupo de data tem o cabeçalho de colunas, com a data na primeira', async () => {
    useSessionsStore(pinia).setForProject(1, [
      makeSession({ session_id: 'a', title: 'Hoje', last_activity_at: now }),
      makeSession({ session_id: 'c', title: 'Velha', last_activity_at: now - 30 * 86400 }),
    ])
    const { wrapper } = await mountList()
    const headers = wrapper.findAll('[data-test="conversations-columns"]')
    expect(headers).toHaveLength(2)
    expect(headers[0]!.text()).toBe('HojeSituaçãoProjetoAtividade')
    expect(headers[0]!.find('[data-test="date-group"]').text()).toBe('Hoje')
    expect(headers[1]!.find('[data-test="date-group"]').text()).toBe('Antes')
    // Below md only the group name stays.
    const rest = headers[0]!.findAll('span').filter((s) => ['Situação', 'Projeto', 'Atividade'].includes(s.text()))
    expect(rest).toHaveLength(3)
    for (const col of rest) expect(col.classes()).toContain('max-xl:hidden')
  })

  it('"Nova conversa" mostra o atalho C e o título não é mais mono maiúsculo', async () => {
    const { wrapper } = await mountList()
    const kbd = wrapper.find('[data-test="conversations-new"] kbd')
    expect(kbd.exists()).toBe(true)
    expect(kbd.text()).toBe('C')
    const h1 = wrapper.find('h1')
    expect(h1.text()).toBe('Conversas')
    expect(h1.classes()).not.toContain('font-mono')
    expect(h1.classes()).not.toContain('uppercase')
  })
})
