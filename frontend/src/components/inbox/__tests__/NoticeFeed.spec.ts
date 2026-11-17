import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import NoticeFeed from '../NoticeFeed.vue'
import { createAppRouter } from '../../../router'
import { formatTime } from '../../../deliveries'
import { useOrgStore } from '../../../stores/org'
import { jsonResponse, makeAgent, makeNotice, makeRun, routeFetch } from '../../../test/factories'

enableAutoUnmount(afterEach)
let pinia: Pinia
const at = (d: number, h: number, m = 0) => new Date(2026, 10, d, h, m).getTime() / 1000

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(new Date(2026, 10, 17, 10, 40))
  pinia = createPinia()
  setActivePinia(pinia)
  useOrgStore(pinia).agents = [makeAgent({ id: 1, name: 'Triagem', project_id: 3 }), makeAgent({ id: 11, name: 'Filmes', project_id: 3 })]
})
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

async function mountFeed() {
  const router = createAppRouter(createMemoryHistory())
  await router.push('/inbox')
  const wrapper = mount(NoticeFeed, { global: { plugins: [pinia, router] }, attachTo: document.body })
  await flushPromises()
  return wrapper
}
type Wrapper = Awaited<ReturnType<typeof mountFeed>>
const rows = (w: Wrapper) => w.findAll('[data-test="agent-notice"]')
const press = async (key: string, target: Element = document.body) => {
  target.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }))
  await flushPromises()
}
function seed() {
  useOrgStore(pinia).notices = [
    makeNotice({ id: 1, agent_id: 1, run_id: 7, text: 'Rotina de hoje.\n\n**Vistas:** 42 itens.', created_at: at(17, 8, 5) }),
    makeNotice({ id: 2, agent_id: 11, run_id: null, text: 'Dois filmes novos.', created_at: at(16, 23), read_at: at(16, 23, 30) }),
    makeNotice({ id: 3, agent_id: 11, run_id: null, kind: 'alert', text: 'Fila travada.', created_at: at(13, 18) }),
    makeNotice({ id: 4, agent_id: 1, run_id: null, text: 'Antiga.', created_at: at(13, 9) }),
  ]
}

describe('NoticeFeed', () => {
  it('sem avisos mostra o estado vazio', async () => {
    const w = await mountFeed()
    expect(w.get('[data-test="notices-empty"]').text()).toBe('Nenhuma novidade dos agentes.')
    expect(w.find('[data-test="notice-feed"]').exists()).toBe(false)
  })

  it('agrupa por dia, do mais novo para o mais antigo, com lidos e não lidos', async () => {
    seed()
    const w = await mountFeed()
    expect(w.findAll('[data-test="notice-day"]').map((d) => d.text())).toEqual(['Hoje', 'Ontem', '13 nov · sexta'])
    expect(rows(w).map((r) => r.get('[data-test="agent-notice-name"]').text())).toEqual(['Triagem', 'Filmes', 'Filmes', 'Triagem'])
    expect(rows(w).map((r) => r.attributes('data-unread'))).toEqual(['true', 'false', 'true', 'true'])
  })

  it('mostra o título e o resumo sem os asteriscos, e a hora', async () => {
    seed()
    const w = await mountFeed()
    const first = rows(w)[0]!
    expect(first.text()).toContain('Rotina de hoje.')
    expect(first.get('[data-test="agent-notice-text"]').text()).toBe('Vistas: 42 itens.')
    expect(first.text()).toContain(formatTime(at(17, 8, 5)))
  })

  it('só o não lido tem a bolinha; o alerta tem o triângulo e o rótulo', async () => {
    seed()
    const w = await mountFeed()
    const [today, yesterday, alert] = rows(w)
    expect(today!.find('[data-test="notice-unread-dot"]').exists()).toBe(true)
    expect(yesterday!.find('[data-test="notice-unread-dot"]').exists()).toBe(false)
    const kind = alert!.get('[data-test="agent-notice-kind"]')
    expect(kind.attributes('data-shape')).toBe('triangle')
    expect(kind.attributes('aria-label')).toBe('Pede atenção')
    expect(today!.find('[data-test="agent-notice-kind"]').exists()).toBe(false)
  })

  it('agente apagado aparece só como "Agente"', async () => {
    useOrgStore(pinia).notices = [makeNotice({ id: 1, agent_id: 99 })]
    const w = await mountFeed()
    expect(w.get('[data-test="agent-notice-name"]').text()).toBe('Agente')
  })

  describe('filtros', () => {
    it('Tudo, um por agente (mais não lidos primeiro) e Pedem atenção, com as contagens de não lidos', async () => {
      seed()
      const w = await mountFeed()
      const chips = w.findAll('[data-test="notice-filter"]')
      expect(chips.map((c) => c.attributes('data-filter'))).toEqual(['all', 'agent-1', 'agent-11', 'alert'])
      expect(chips.map((c) => c.get('[data-test="filter-chip-count"]').text())).toEqual(['3', '2', '1', '1'])
      expect(chips[0]!.attributes('aria-pressed')).toBe('true')
    })

    it('escolher um agente mostra só os avisos dele; tocar de novo volta para Tudo', async () => {
      seed()
      const w = await mountFeed()
      await w.get('[data-filter="agent-11"]').trigger('click')
      expect(rows(w)).toHaveLength(2)
      expect(w.get('[data-filter="agent-11"]').attributes('aria-pressed')).toBe('true')
      expect(w.get('[data-filter="all"]').attributes('aria-pressed')).toBe('false')
      await w.get('[data-filter="agent-11"]').trigger('click')
      expect(rows(w)).toHaveLength(4)
    })

    it('Pedem atenção mostra só os alertas', async () => {
      seed()
      const w = await mountFeed()
      await w.get('[data-filter="alert"]').trigger('click')
      expect(rows(w)).toHaveLength(1)
      expect(rows(w)[0]!.text()).toContain('Fila travada.')
    })

    it('sem alertas não há o filtro de atenção', async () => {
      useOrgStore(pinia).notices = [makeNotice({ id: 1 })]
      const w = await mountFeed()
      expect(w.find('[data-filter="alert"]').exists()).toBe(false)
    })
  })

  describe('seleção', () => {
    it('clicar num aviso o seleciona e mostra as ações', async () => {
      seed()
      const w = await mountFeed()
      expect(w.find('[data-test="notice-read-full"]').exists()).toBe(false)
      await rows(w)[0]!.trigger('click')
      const first = rows(w)[0]!
      expect(first.attributes('data-selected')).toBe('true')
      expect(first.get('[data-test="notice-read-full"]').text()).toBe('Ler tudo aqui')
      expect(first.get('[data-test="agent-notice-open"]').attributes('href')).toBe('/agentes/3?agente=1')
      expect(first.find('[data-test="agent-notice-read"]').exists()).toBe(true)
      expect(rows(w)[1]!.attributes('data-selected')).toBe('false')
    })

    it('"Ler tudo aqui" some quando o aviso não tem nada além do título', async () => {
      useOrgStore(pinia).notices = [makeNotice({ id: 1, text: 'Só o título.', created_at: at(17, 9) }), makeNotice({ id: 2, text: 'Título\n\nCom corpo.', created_at: at(17, 8) })]
      const w = await mountFeed()
      await rows(w)[0]!.trigger('click')
      expect(w.find('[data-test="notice-read-full"]').exists()).toBe(false)
      expect(rows(w)[0]!.find('[data-test="agent-notice-open"]').exists()).toBe(true)
      await rows(w)[1]!.trigger('click')
      expect(w.find('[data-test="notice-read-full"]').exists()).toBe(true)
    })

    it('o aviso lido não tem "Marcar como lido"', async () => {
      seed()
      const w = await mountFeed()
      await rows(w)[1]!.trigger('click')
      expect(rows(w)[1]!.find('[data-test="agent-notice-read"]').exists()).toBe(false)
    })

    it('"Abrir conversa da execução" aparece quando a execução do aviso tem conversa', async () => {
      seed()
      useOrgStore(pinia).runs = { 1: [makeRun({ id: 7, agent_id: 1, session_id: 'sess-7' })] }
      const w = await mountFeed()
      await rows(w)[0]!.trigger('click')
      expect(w.get('[data-test="notice-open-run"]').attributes('href')).toBe('/sessions/sess-7')
    })

    it('sem conversa na execução, o botão não aparece', async () => {
      seed()
      useOrgStore(pinia).runs = { 1: [makeRun({ id: 7, agent_id: 1, session_id: null })] }
      const w = await mountFeed()
      await rows(w)[0]!.trigger('click')
      expect(w.find('[data-test="notice-open-run"]').exists()).toBe(false)
    })

    it('carrega as execuções do agente uma vez ao selecionar um aviso com execução', async () => {
      seed()
      const fetch = routeFetch({ 'GET /api/agents/1/runs?limit=50': () => jsonResponse([makeRun({ id: 7, agent_id: 1, session_id: 'sess-7' })]) })
      vi.stubGlobal('fetch', fetch)
      const w = await mountFeed()
      await rows(w)[0]!.trigger('click')
      await flushPromises()
      await rows(w)[3]!.trigger('click')
      await rows(w)[0]!.trigger('click')
      await flushPromises()
      expect(fetch.mock.calls.filter(([url]) => String(url).startsWith('/api/agents/1/runs'))).toHaveLength(1)
      expect(w.get('[data-test="notice-open-run"]').attributes('href')).toBe('/sessions/sess-7')
    })

    it('aviso sem execução não carrega nada', async () => {
      seed()
      const fetch = routeFetch({})
      vi.stubGlobal('fetch', fetch)
      const w = await mountFeed()
      await rows(w)[1]!.trigger('click')
      expect(fetch).not.toHaveBeenCalled()
    })

    it('"Ler tudo aqui" tira o corte de duas linhas e mostra os parágrafos', async () => {
      useOrgStore(pinia).notices = [makeNotice({ id: 1, text: 'Título\n\nPrimeiro.\n\nSegundo.' })]
      const w = await mountFeed()
      await rows(w)[0]!.trigger('click')
      expect(w.get('[data-test="agent-notice-text"]').classes()).toContain('line-clamp-2')
      await w.get('[data-test="notice-read-full"]').trigger('click')
      const text = w.get('[data-test="agent-notice-text"]')
      expect(text.classes()).not.toContain('line-clamp-2')
      expect(text.element.textContent).toBe('Primeiro.\n\nSegundo.')
      expect(w.get('[data-test="notice-read-full"]').attributes('aria-expanded')).toBe('true')
    })

    it('escolher outro aviso recolhe o texto', async () => {
      seed()
      const w = await mountFeed()
      await rows(w)[0]!.trigger('click')
      await w.get('[data-test="notice-read-full"]').trigger('click')
      await rows(w)[3]!.trigger('click')
      await rows(w)[0]!.trigger('click')
      expect(rows(w)[0]!.get('[data-test="agent-notice-text"]').classes()).toContain('line-clamp-2')
    })
  })

  describe('teclado', () => {
    it('j seleciona o primeiro e depois o próximo; k volta', async () => {
      seed()
      const w = await mountFeed()
      await press('j')
      expect(rows(w).map((r) => r.attributes('data-selected'))).toEqual(['true', 'false', 'false', 'false'])
      await press('j')
      expect(rows(w).map((r) => r.attributes('data-selected'))).toEqual(['false', 'true', 'false', 'false'])
      await press('k')
      expect(rows(w)[0]!.attributes('data-selected')).toBe('true')
      await press('k')
      expect(rows(w)[0]!.attributes('data-selected')).toBe('true')
    })

    it('k sem seleção seleciona o primeiro, e j no último fica nele', async () => {
      seed()
      const w = await mountFeed()
      await press('k')
      expect(rows(w)[0]!.attributes('data-selected')).toBe('true')
      for (let i = 0; i < 6; i++) await press('j')
      expect(rows(w)[3]!.attributes('data-selected')).toBe('true')
    })

    it('anda só pelos avisos do filtro', async () => {
      seed()
      const w = await mountFeed()
      await w.get('[data-filter="agent-11"]').trigger('click')
      await press('j')
      await press('j')
      expect(rows(w)[1]!.attributes('data-selected')).toBe('true')
      await press('j')
      expect(rows(w)[1]!.attributes('data-selected')).toBe('true')
    })

    it('Enter alterna o texto inteiro do selecionado', async () => {
      seed()
      const w = await mountFeed()
      await press('Enter')
      expect(w.find('[data-test="notice-read-full"]').exists()).toBe(false)
      await press('j')
      await press('Enter')
      expect(w.get('[data-test="agent-notice-text"]').classes()).not.toContain('line-clamp-2')
      await press('Enter')
      expect(w.get('[data-test="agent-notice-text"]').classes()).toContain('line-clamp-2')
    })

    it('Enter num botão ou link não alterna o texto', async () => {
      seed()
      const w = await mountFeed()
      await press('j')
      await press('Enter', w.get('[data-test="agent-notice-open"]').element)
      expect(w.get('[data-test="agent-notice-text"]').classes()).toContain('line-clamp-2')
    })

    it('e marca o selecionado como lido pela API', async () => {
      const bodies: unknown[] = []
      vi.stubGlobal('fetch', routeFetch({
        'POST /api/agent-notices/read': (init) => {
          bodies.push(JSON.parse(String(init?.body)))
          return jsonResponse({ updated: 1 })
        },
      }))
      seed()
      const w = await mountFeed()
      await press('e')
      expect(bodies).toEqual([])
      await press('j')
      await press('e')
      expect(bodies).toEqual([{ ids: [1] }])
      expect(rows(w)[0]!.attributes('data-unread')).toBe('false')
      await press('e')
      expect(bodies).toHaveLength(1)
    })

    it('com o foco num campo, nada acontece', async () => {
      seed()
      const w = await mountFeed()
      const input = document.createElement('input')
      document.body.appendChild(input)
      input.focus()
      await press('j', input)
      await press('e', input)
      expect(rows(w).every((r) => r.attributes('data-selected') === 'false')).toBe(true)
      input.remove()
    })

    it('depois de desmontar, as teclas não agem', async () => {
      seed()
      const w = await mountFeed()
      w.unmount()
      await press('j')
      expect(document.querySelector('[data-test="agent-notice"]')).toBeNull()
    })

    it('tem a legenda das teclas', async () => {
      seed()
      const w = await mountFeed()
      const keys = w.get('[data-test="notice-keys"]')
      expect(keys.text()).toContain('navegar')
      expect(keys.text()).toContain('ler aqui')
      expect(keys.text()).toContain('marcar como lida')
    })
  })

  describe('marcar como lido', () => {
    it('"Marcar como lido" marca só aquele aviso', async () => {
      const bodies: unknown[] = []
      vi.stubGlobal('fetch', routeFetch({
        'POST /api/agent-notices/read': (init) => {
          bodies.push(JSON.parse(String(init?.body)))
          return jsonResponse({ updated: 1 })
        },
      }))
      seed()
      const w = await mountFeed()
      await rows(w)[3]!.trigger('click')
      await w.get('[data-test="agent-notice-read"]').trigger('click')
      await flushPromises()
      expect(bodies).toEqual([{ ids: [4] }])
      expect(rows(w)).toHaveLength(4)
      expect(rows(w)[3]!.attributes('data-unread')).toBe('false')
    })

    it('"Marcar todas como lidas" marca os não lidos do filtro atual', async () => {
      const bodies: unknown[] = []
      vi.stubGlobal('fetch', routeFetch({
        'POST /api/agent-notices/read': (init) => {
          bodies.push(JSON.parse(String(init?.body)))
          return jsonResponse({ updated: 2 })
        },
      }))
      seed()
      const w = await mountFeed()
      await w.get('[data-filter="agent-1"]').trigger('click')
      await w.get('[data-test="agent-notices-read-all"]').trigger('click')
      await flushPromises()
      expect(bodies).toEqual([{ ids: [1, 4] }])
      expect(useOrgStore(pinia).unreadCount).toBe(1)
    })

    it('"Marcar todas como lidas" some quando não há não lidos no filtro', async () => {
      useOrgStore(pinia).notices = [makeNotice({ id: 1, read_at: 5 })]
      const w = await mountFeed()
      expect(w.find('[data-test="agent-notices-read-all"]').exists()).toBe(false)
    })

    it('falha da API mostra o erro e mantém o aviso não lido', async () => {
      vi.stubGlobal('fetch', routeFetch({ 'POST /api/agent-notices/read': () => jsonResponse({ detail: 'Deu ruim' }, 500) }))
      useOrgStore(pinia).notices = [makeNotice({ id: 1 })]
      const w = await mountFeed()
      await rows(w)[0]!.trigger('click')
      await w.get('[data-test="agent-notice-read"]').trigger('click')
      await flushPromises()
      expect(w.get('[data-test="agent-notices-error"]').text()).toContain('Deu ruim')
      expect(rows(w)[0]!.attributes('data-unread')).toBe('true')
    })
  })
})
