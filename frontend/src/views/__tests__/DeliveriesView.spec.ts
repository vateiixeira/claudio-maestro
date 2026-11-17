import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import DeliveriesView from '../DeliveriesView.vue'
import { createAppRouter } from '../../router'
import { formatDayLong, formatTime, localDay, projectMarkdown, shiftDay } from '../../deliveries'
import { useDeliveriesStore } from '../../stores/deliveries'
import { useLabelsStore } from '../../stores/labels'
import { useProjectsStore } from '../../stores/projects'
import { useSessionsStore } from '../../stores/sessions'
import { jsonResponse, makeLabel, makeProject, makeSession, routeFetch } from '../../test/factories'
import type { DeliveriesDay, Delivery } from '../../types/api'

vi.mock('../../stores/realtime', () => ({ loadEverything: vi.fn(() => Promise.resolve()) }))

enableAutoUnmount(afterEach)
let pinia: Pinia
const today = localDay()

function delivery(over: Partial<Delivery> = {}): Delivery {
  return { id: 1, session_id: 's1', project_id: 1, project_name: 'app', title: 'Conversa', finished_at: Math.floor(Date.now() / 1000),
    status: 'done', summary_title: 'Leitura de markdown', bullets: ['Rota', 'Página'], error: null, ...over }
}
function dayOf(date: string, over: Partial<DeliveriesDay> = {}): DeliveriesDay {
  return { date, agent_enabled: true, deliveries: [], in_progress: [], prev_day: null, next_day: null, ...over }
}

beforeEach(() => {
  localStorage.clear()
  pinia = createPinia()
  setActivePinia(pinia)
})
afterEach(() => vi.unstubAllGlobals())

async function mountAt(path: string, routes: Record<string, () => Response | Promise<Response>>) {
  const fetch = routeFetch(routes)
  vi.stubGlobal('fetch', fetch)
  const router = createAppRouter(createMemoryHistory())
  await router.push(path)
  const wrapper = mount(DeliveriesView, { global: { plugins: [pinia, router] } })
  await flushPromises()
  return { wrapper, fetch, router }
}

describe('Entregas', () => {
  it('mostra hoje numa linha do tempo, com tópicos e link para a conversa', async () => {
    localStorage.setItem('maestro:deliveries-detail', 'true')
    const { wrapper } = await mountAt('/entregas', {
      [`GET /api/deliveries?date=${today}`]: () => jsonResponse(dayOf(today, {
        deliveries: [delivery(), delivery({ id: 2, project_name: 'b', session_id: null, summary_title: null, title: 'Antiga', bullets: [], status: 'title_only' })],
      })),
    })
    const first = wrapper.findAll('[data-test="delivery"]')[0]!
    expect(first.find('a').attributes('href')).toBe('/sessions/s1')
    expect(first.findAll('li').map((li) => li.text())).toEqual(['Rota', 'Página'])
    // sem link quando a conversa não existe mais
    expect(wrapper.findAll('[data-test="delivery"]')[1]!.find('a').exists()).toBe(false)
  })

  it.each([['2026-13-45', 'inexistente'], ['2026-02-30', 'que não existe'], ['2099-01-01', 'no futuro'], ['abc', 'fora do formato']])('?dia=%s (%s) cai em hoje', async (bad) => {
    const { wrapper, fetch } = await mountAt(`/entregas?dia=${bad}`, {
      [`GET /api/deliveries?date=${today}`]: () => jsonResponse(dayOf(today)),
    })
    expect(wrapper.get('h1').text()).toBe(formatDayLong(today))
    expect(fetch.mock.calls.map(([url]) => url)).toEqual([`/api/deliveries?date=${today}`])
    expect(wrapper.get('[data-test="next-day"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-test="today"]').attributes('disabled')).toBeDefined()
  })

  it('anda entre dias pela query e desabilita o próximo em hoje', async () => {
    const yesterday = new Date(); yesterday.setDate(yesterday.getDate() - 1)
    const y = localDay(yesterday)
    const { wrapper, router } = await mountAt('/entregas', {
      [`GET /api/deliveries?date=${today}`]: () => jsonResponse(dayOf(today)),
      [`GET /api/deliveries?date=${y}`]: () => jsonResponse(dayOf(y)),
    })
    expect(wrapper.find('[data-test="next-day"]').attributes('disabled')).toBeDefined()
    await wrapper.find('[data-test="prev-day"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.query.dia).toBe(y)
    await wrapper.find('[data-test="today"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.query.dia).toBeUndefined()
  })

  it('mostra os estados de cada registro', async () => {
    const { wrapper } = await mountAt('/entregas', {
      [`GET /api/deliveries?date=${today}`]: () => jsonResponse(dayOf(today, {
        deliveries: [
          delivery({ id: 1, status: 'pending', summary_title: null, bullets: [] }),
          delivery({ id: 2, status: 'error', error: 'Limite atingido.' }),
          delivery({ id: 3, status: 'title_only', summary_title: null, bullets: [] }),
        ],
      })),
      'POST /api/deliveries/2/summarize': () => jsonResponse(delivery({ id: 2, status: 'pending' })),
    })
    const items = wrapper.findAll('[data-test="delivery"]')
    expect(items[0]!.text()).toContain('Resumindo…')
    expect(items[1]!.text()).toContain('Limite atingido.')
    expect(items[2]!.find('[data-test="summarize"]').text()).toBe('Resumir')
    await items[1]!.find('[data-test="summarize"]').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('[data-test="delivery"]')[1]!.text()).toContain('Resumindo…')
  })

  it('esconde "Resumir" com o agente desligado', async () => {
    const { wrapper } = await mountAt('/entregas', {
      [`GET /api/deliveries?date=${today}`]: () => jsonResponse(dayOf(today, {
        agent_enabled: false, deliveries: [delivery({ status: 'title_only', summary_title: null, bullets: [] })],
      })),
    })
    expect(wrapper.find('[data-test="summarize"]').exists()).toBe(false)
  })

  it('mostra "Em andamento" e o dia vazio', async () => {
    const { wrapper } = await mountAt('/entregas', {
      [`GET /api/deliveries?date=${today}`]: () => jsonResponse(dayOf(today, {
        in_progress: [{ session_id: 'x', project_id: 1, project_name: 'app', title: 'Tela', short: 'Faz a rota' }],
      })),
    })
    expect(wrapper.text()).toContain('Nada finalizado neste dia.')
    const open = wrapper.find('[data-test="in-progress"]')
    expect(open.text()).toContain('Tela')
    expect(open.find('a').attributes('title')).toBe('Faz a rota')
  })

  it('copia o markdown do dia', async () => {
    const writeText = vi.fn(() => Promise.resolve())
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } })
    const { wrapper } = await mountAt('/entregas', {
      [`GET /api/deliveries?date=${today}`]: () => jsonResponse(dayOf(today, { deliveries: [delivery()] })),
    })
    await wrapper.find('[data-test="copy"]').trigger('click')
    await flushPromises()
    expect(writeText).toHaveBeenCalledWith(expect.stringContaining('**Leitura de markdown**\n- Rota'))
    expect(wrapper.find('[data-test="copy"]').text()).toBe('Copiado')
  })
  it('a linha do tempo lista as entregas em ordem de horário, sem raias', async () => {
    useProjectsStore(pinia).projects = [makeProject({ id: 1, name: 'app', color: '#B28CFF' })]
    const t = Math.floor(Date.now() / 1000)
    const { wrapper } = await mountAt('/entregas', {
      [`GET /api/deliveries?date=${today}`]: () => jsonResponse(dayOf(today, {
        deliveries: [
          delivery({ id: 1, finished_at: t, summary_title: 'Última' }),
          delivery({ id: 2, finished_at: t - 7200, project_id: 99, project_name: 'b', summary_title: 'Primeira', session_id: null }),
        ],
      })),
    })
    const timeline = wrapper.get('[data-test="delivery-timeline"]')
    const rows = timeline.findAll('[data-test="delivery"]')
    expect(rows.map((r) => r.attributes('data-delivery-id'))).toEqual(['2', '1'])
    expect(rows[0]!.get('[data-test="delivery-time"]').text()).toBe(formatTime(t - 7200))
    expect(rows[0]!.get('h2').text()).toBe('Primeira')
    expect(rows[1]!.get('[data-test="project-tag"]').text()).toBe('app')
    // projeto desconhecido: nome sem cor própria, ponto neutro
    expect(rows[0]!.get('[data-test="project-tag"]').text()).toBe('b')
    expect((rows[1]!.get('[data-test="delivery-dot"]').element as HTMLElement).style.backgroundColor).not.toBe('')
    expect((rows[0]!.get('[data-test="delivery-dot"]').element as HTMLElement).style.backgroundColor).toBe('')
    expect(wrapper.find('[data-test="delivery-group"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="delivery-grid"]').exists()).toBe(false)
  })

  it('"Em andamento" é uma coluna fixa ao lado da linha do tempo', async () => {
    const { wrapper } = await mountAt('/entregas', {
      [`GET /api/deliveries?date=${today}`]: () => jsonResponse(dayOf(today, {
        deliveries: [delivery()],
        in_progress: [{ session_id: 'x', project_id: 1, project_name: 'app', title: 'Tela', short: 'Faz a rota' }],
      })),
    })
    const lane = wrapper.get('[data-test="in-progress"]')
    expect(lane.classes()).toEqual(expect.arrayContaining(['md:shrink-0']))
    const board = wrapper.get('[data-test="delivery-timeline"]').element.parentElement!
    expect(board.classList.contains('min-w-0') && board.classList.contains('flex-1')).toBe(true)
    expect(board.nextElementSibling).toBe(lane.element)
    expect(board.parentElement!.classList.contains('md:flex-row')).toBe(true)
  })

  it('a página não é limitada nem centralizada', async () => {
    const { wrapper } = await mountAt('/entregas', { [`GET /api/deliveries?date=${today}`]: () => jsonResponse(dayOf(today)) })
    expect(wrapper.classes()).not.toContain('max-w-7xl')
    expect(wrapper.classes()).not.toContain('mx-auto')
  })

  it('o registro não tem borda nem cartão', async () => {
    const { wrapper } = await mountAt('/entregas', {
      [`GET /api/deliveries?date=${today}`]: () => jsonResponse(dayOf(today, { deliveries: [delivery(), delivery({ id: 2 })] })),
    })
    for (const item of wrapper.findAll('[data-test="delivery"]')) {
      expect(item.classes()).not.toContain('border')
      expect(item.classes()).not.toContain('border-t')
    }
  })

  it('"Em andamento" tem o ícone de execução, a contagem e os itens como links, só com quadradinho e título', async () => {
    useProjectsStore(pinia).projects = [makeProject({ id: 1, name: 'app', color: '#B28CFF' })]
    const { wrapper } = await mountAt('/entregas', {
      [`GET /api/deliveries?date=${today}`]: () => jsonResponse(dayOf(today, {
        in_progress: [
          { session_id: 'x', project_id: 1, project_name: 'app', title: 'Tela', short: 'Faz a rota' },
          { session_id: 'y', project_id: 1, project_name: 'app', title: 'Outra', short: null },
        ],
      })),
    })
    const lane = wrapper.get('[data-test="in-progress"]')
    expect(lane.find('[data-shape="spinner"]').exists()).toBe(true)
    expect(lane.get('[data-test="lane-count"]').text()).toBe('2')
    const items = lane.findAll('a')
    expect(items.map((a) => a.attributes('href'))).toEqual(['/sessions/x', '/sessions/y'])
    expect(items[0]!.text()).toBe('Tela')
    expect(items[0]!.attributes('title')).toBe('Faz a rota')
    expect((items[0]!.get('span').element as HTMLElement).style.backgroundColor).not.toBe('')
    expect(lane.find('[data-test="label-badges"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('Nada finalizado neste dia.')
    expect(wrapper.find('[data-test="delivery-timeline"]').exists()).toBe(false)
  })

  it('mostra só o primeiro tópico e abre o resto em "Mais N itens"', async () => {
    const { wrapper } = await mountAt('/entregas', {
      [`GET /api/deliveries?date=${today}`]: () => jsonResponse(dayOf(today, { deliveries: [delivery({ bullets: ['a', 'b', 'c', 'd', 'e'] })] })),
    })
    expect(wrapper.findAll('[data-test="delivery"] li').map((li) => li.text())).toEqual(['a'])
    const more = wrapper.get('[data-test="more-bullets"]')
    expect(more.text()).toBe('Mais 4 itens')
    expect(more.attributes('aria-expanded')).toBe('false')
    await more.trigger('click')
    expect(wrapper.findAll('[data-test="delivery"] li')).toHaveLength(5)
    expect(wrapper.get('[data-test="more-bullets"]').text()).toBe('Mostrar menos')
    expect(wrapper.get('[data-test="more-bullets"]').attributes('aria-expanded')).toBe('true')
    await wrapper.get('[data-test="more-bullets"]').trigger('click')
    expect(wrapper.findAll('[data-test="delivery"] li')).toHaveLength(1)
  })

  it('"Mais 1 item" no singular e sem botão com um tópico só', async () => {
    const two = await mountAt('/entregas', {
      [`GET /api/deliveries?date=${today}`]: () => jsonResponse(dayOf(today, { deliveries: [delivery({ bullets: ['a', 'b'] })] })),
    })
    expect(two.wrapper.get('[data-test="more-bullets"]').text()).toBe('Mais 1 item')
    const one = await mountAt('/entregas', {
      [`GET /api/deliveries?date=${today}`]: () => jsonResponse(dayOf(today, { deliveries: [delivery({ bullets: ['a'] })] })),
    })
    expect(one.wrapper.find('[data-test="more-bullets"]').exists()).toBe(false)
  })

  it('o alternador abre todos os tópicos e guarda a escolha', async () => {
    const routes = { [`GET /api/deliveries?date=${today}`]: () => jsonResponse(dayOf(today, { deliveries: [delivery({ bullets: ['a', 'b', 'c'] })] })) }
    const { wrapper } = await mountAt('/entregas', routes)
    const toggle = wrapper.get('[data-test="toggle-detail"]')
    expect(toggle.attributes('aria-pressed')).toBe('false')
    expect(toggle.text()).toBe('Resumido')
    await toggle.trigger('click')
    expect(wrapper.get('[data-test="toggle-detail"]').attributes('aria-pressed')).toBe('true')
    expect(wrapper.get('[data-test="toggle-detail"]').text()).toBe('Detalhado')
    expect(wrapper.findAll('[data-test="delivery"] li')).toHaveLength(3)
    expect(wrapper.find('[data-test="more-bullets"]').exists()).toBe(false)
    expect(localStorage.getItem('maestro:deliveries-detail')).toBe('true')
    // a próxima visita já começa detalhada
    const again = await mountAt('/entregas', routes)
    expect(again.wrapper.get('[data-test="toggle-detail"]').attributes('aria-pressed')).toBe('true')
    expect(again.wrapper.findAll('[data-test="delivery"] li')).toHaveLength(3)
  })

  it('o alternador fica à esquerda da navegação de dias', async () => {
    const { wrapper } = await mountAt('/entregas', { [`GET /api/deliveries?date=${today}`]: () => jsonResponse(dayOf(today)) })
    const toggle = wrapper.get('[data-test="toggle-detail"]').element
    const nav = wrapper.get('[data-test="day-nav"]').element
    expect(toggle.compareDocumentPosition(nav) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('o horário fica numa coluna fixa antes do título', async () => {
    const { wrapper } = await mountAt('/entregas', {
      [`GET /api/deliveries?date=${today}`]: () => jsonResponse(dayOf(today, { deliveries: [delivery()] })),
    })
    const item = wrapper.get('[data-test="delivery"]')
    const time = item.get('[data-test="delivery-time"]')
    expect(time.classes()).toEqual(expect.arrayContaining(['tabular-nums']))
    expect(time.text()).toBe(formatTime(delivery().finished_at))
    expect(time.element.compareDocumentPosition(item.get('a').element) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('cada estado tem a sua forma', async () => {
    const { wrapper } = await mountAt('/entregas', {
      [`GET /api/deliveries?date=${today}`]: () => jsonResponse(dayOf(today, {
        deliveries: [
          delivery({ id: 1, status: 'pending', summary_title: null, bullets: [] }),
          delivery({ id: 2, status: 'error', error: 'Limite atingido.' }),
          delivery({ id: 3, status: 'title_only', summary_title: null, bullets: [] }),
          delivery({ id: 4 }),
        ],
      })),
    })
    const items = wrapper.findAll('[data-test="delivery"]')
    expect(items[0]!.find('[data-shape="spinner"]').exists()).toBe(true)
    expect(items[1]!.find('[data-test="error-icon"]').exists()).toBe(true)
    expect(items[2]!.text()).toContain('só título')
    expect(items[0]!.text()).not.toContain('só título')
    expect(items[3]!.text()).not.toContain('só título')
  })

  it('desabilita "Resumir" enquanto o pedido roda', async () => {
    let release!: () => void
    const gate = new Promise<void>((resolve) => { release = resolve })
    const { wrapper } = await mountAt('/entregas', {
      [`GET /api/deliveries?date=${today}`]: () => jsonResponse(dayOf(today, { deliveries: [delivery({ status: 'title_only', summary_title: null, bullets: [] })] })),
      'POST /api/deliveries/1/summarize': () => gate.then(() => jsonResponse(delivery({ status: 'pending' }))),
    })
    await wrapper.get('[data-test="summarize"]').trigger('click')
    expect(wrapper.get('[data-test="summarize"]').attributes('disabled')).toBeDefined()
    release()
    await flushPromises()
    expect(wrapper.find('[data-test="summarize"]').exists()).toBe(false)
  })

  it('resume o dia: entregas, projetos e o que ainda está resumindo', async () => {
    const many = await mountAt('/entregas', {
      [`GET /api/deliveries?date=${today}`]: () => jsonResponse(dayOf(today, {
        deliveries: [delivery({ id: 1 }), delivery({ id: 2 }), delivery({ id: 3, project_name: 'b', status: 'pending' }), delivery({ id: 4, project_name: 'c', status: 'pending' })],
      })),
    })
    expect(many.wrapper.get('[data-test="day-summary"]').text()).toBe('4 entregas em 3 projetos. 2 resumos ainda sendo escritos.')
    const one = await mountAt('/entregas', {
      [`GET /api/deliveries?date=${today}`]: () => jsonResponse(dayOf(today, { deliveries: [delivery()] })),
    })
    expect(one.wrapper.get('[data-test="day-summary"]').text()).toBe('1 entrega em 1 projeto.')
    expect(one.wrapper.find('[data-test="pending-count"]').exists()).toBe(false)
  })

  it('o resumo do dia vazio', async () => {
    const { wrapper } = await mountAt('/entregas', { [`GET /api/deliveries?date=${today}`]: () => jsonResponse(dayOf(today)) })
    expect(wrapper.get('[data-test="day-summary"]').text()).toBe('Nenhuma entrega.')
  })

  it('a navegação é um controle segmentado e "Hoje" desligado não parece quebrado', async () => {
    const { wrapper } = await mountAt('/entregas', { [`GET /api/deliveries?date=${today}`]: () => jsonResponse(dayOf(today)) })
    const nav = wrapper.get('[data-test="day-nav"]')
    expect(nav.classes()).toContain('border-line-strong')
    expect(nav.classes()).toContain('rounded-md')
    expect(nav.findAll('button').map((b) => b.attributes('data-test'))).toEqual(['prev-day', 'today', 'next-day'])
    const todayButton = wrapper.get('[data-test="today"]')
    expect(todayButton.attributes('disabled')).toBeDefined()
    expect(todayButton.classes()).toContain('disabled:text-fg-subtle')
    expect(todayButton.classes().join(' ')).not.toContain('opacity')
  })

  it('desabilita "Copiar" no dia vazio e anuncia a cópia', async () => {
    const writeText = vi.fn(() => Promise.resolve())
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } })
    const empty = await mountAt('/entregas', { [`GET /api/deliveries?date=${today}`]: () => jsonResponse(dayOf(today)) })
    expect(empty.wrapper.get('[data-test="copy"]').attributes('disabled')).toBeDefined()
    const full = await mountAt('/entregas', { [`GET /api/deliveries?date=${today}`]: () => jsonResponse(dayOf(today, { deliveries: [delivery()] })) })
    expect(full.wrapper.get('[data-test="copy-status"]').text()).toBe('')
    await full.wrapper.get('[data-test="copy"]').trigger('click')
    await flushPromises()
    expect(full.wrapper.get('[data-test="copy-status"]').text()).toBe('Copiado')
    expect(full.wrapper.get('[data-test="copy-status"]').attributes('aria-live')).toBe('polite')
  })

  it('só com "Em andamento" o "Copiar" fica habilitado', async () => {
    const { wrapper } = await mountAt('/entregas', {
      [`GET /api/deliveries?date=${today}`]: () => jsonResponse(dayOf(today, {
        in_progress: [{ session_id: 'x', project_id: 1, project_name: 'app', title: 'Tela', short: null }],
      })),
    })
    expect(wrapper.get('[data-test="copy"]').attributes('disabled')).toBeUndefined()
  })

  it('a data é o título da página', async () => {
    const { wrapper } = await mountAt('/entregas', { [`GET /api/deliveries?date=${today}`]: () => jsonResponse(dayOf(today)) })
    expect(wrapper.get('h1').text()).toBe(formatDayLong(today))
  })

  it('mantém o dia anterior apagado e ocupado até a resposta do novo chegar', async () => {
    const yesterday = new Date(); yesterday.setDate(yesterday.getDate() - 1)
    const y = localDay(yesterday)
    let release!: () => void
    const gate = new Promise<void>((resolve) => { release = resolve })
    const { wrapper } = await mountAt('/entregas', {
      [`GET /api/deliveries?date=${today}`]: () => jsonResponse(dayOf(today, { deliveries: [delivery()] })),
      [`GET /api/deliveries?date=${y}`]: () => gate.then(() => jsonResponse(dayOf(y))),
    })
    await wrapper.get('[data-test="prev-day"]').trigger('click')
    await flushPromises()
    const content = wrapper.get('[data-test="day-content"]')
    expect(content.attributes('aria-busy')).toBe('true')
    expect(content.classes()).toContain('opacity-60')
    expect(wrapper.findAll('[data-test="delivery"]')).toHaveLength(1)
    release()
    await flushPromises()
    expect(wrapper.get('[data-test="day-content"]').attributes('aria-busy')).not.toBe('true')
    expect(wrapper.findAll('[data-test="delivery"]')).toHaveLength(0)
  })

  it('no primeiro carregamento mostra o LoadStatus', async () => {
    vi.stubGlobal('fetch', routeFetch({ [`GET /api/deliveries?date=${today}`]: () => new Promise<Response>(() => {}) }))
    const router = createAppRouter(createMemoryHistory())
    await router.push('/entregas')
    const wrapper = mount(DeliveriesView, { global: { plugins: [pinia, router] } })
    await flushPromises()
    expect(wrapper.find('[data-test="load-loading"]').exists()).toBe(true)
  })

  it('num erro de carregamento mostra a mensagem e "Tentar de novo"', async () => {
    let calls = 0
    const { wrapper } = await mountAt('/entregas', {
      [`GET /api/deliveries?date=${today}`]: () => (++calls === 1 ? jsonResponse({ detail: 'Falhou ao ler.' }, 500) : jsonResponse(dayOf(today, { deliveries: [delivery()] }))),
    })
    expect(wrapper.text()).toContain('Falhou ao ler.')
    await wrapper.get('[data-test="retry-day"]').trigger('click')
    await flushPromises()
    expect(calls).toBe(2)
    expect(wrapper.find('[data-test="retry-day"]').exists()).toBe(false)
    expect(wrapper.findAll('[data-test="delivery"]')).toHaveLength(1)
  })

  it('volta o botão para "Copiar o dia" depois de 2 segundos e limpa o timer ao trocar de dia', async () => {
    const writeText = vi.fn(() => Promise.resolve())
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } })
    const yesterday = new Date(); yesterday.setDate(yesterday.getDate() - 1)
    const y = localDay(yesterday)
    const { wrapper } = await mountAt('/entregas', {
      [`GET /api/deliveries?date=${today}`]: () => jsonResponse(dayOf(today, { deliveries: [delivery()] })),
      [`GET /api/deliveries?date=${y}`]: () => jsonResponse(dayOf(y)),
    })
    vi.useFakeTimers()
    try {
      await wrapper.find('[data-test="copy"]').trigger('click')
      await vi.advanceTimersByTimeAsync(0)
      expect(wrapper.find('[data-test="copy"]').text()).toBe('Copiado')
      await vi.advanceTimersByTimeAsync(1900)
      expect(wrapper.find('[data-test="copy"]').text()).toBe('Copiado')
      await vi.advanceTimersByTimeAsync(200)
      expect(wrapper.find('[data-test="copy"]').text()).toBe('Copiar o dia')

      // trocar de dia limpa o timer pendente
      await wrapper.find('[data-test="copy"]').trigger('click')
      await vi.advanceTimersByTimeAsync(0)
      expect(vi.getTimerCount()).toBeGreaterThan(0)
      await wrapper.find('[data-test="prev-day"]').trigger('click')
      await vi.advanceTimersByTimeAsync(0)
      expect(wrapper.find('[data-test="copy"]').text()).toBe('Copiar o dia')
      expect(vi.getTimerCount()).toBe(0)
      wrapper.unmount()
    } finally {
      vi.useRealTimers()
    }
  })
  it('o resumo do dia no singular de resumo pendente', async () => {
    const { wrapper } = await mountAt('/entregas', {
      [`GET /api/deliveries?date=${today}`]: () => jsonResponse(dayOf(today, { deliveries: [delivery({ status: 'pending' })] })),
    })
    expect(wrapper.get('[data-test="day-summary"]').text()).toBe('1 entrega em 1 projeto. 1 resumo ainda sendo escrito.')
  })

  describe('régua do dia', () => {
    const at = (h: number, m = 0) => Math.floor(new Date(2026, 9, 7, h, m).getTime() / 1000)
    const ranged = () => ({
      [`GET /api/deliveries?date=${today}`]: () => jsonResponse(dayOf(today, {
        deliveries: [
          delivery({ id: 1, finished_at: at(10, 42), project_id: 1 }),
          delivery({ id: 2, finished_at: at(14, 23), project_id: 99, project_name: 'b', summary_title: 'Outra' }),
        ],
      })),
    })

    it('não aparece sem entregas', async () => {
      const { wrapper } = await mountAt('/entregas', { [`GET /api/deliveries?date=${today}`]: () => jsonResponse(dayOf(today)) })
      expect(wrapper.find('[data-test="day-ruler"]').exists()).toBe(false)
    })

    it('marca cada entrega, na cor do projeto, com rótulo e título', async () => {
      useProjectsStore(pinia).projects = [makeProject({ id: 1, name: 'app', color: '#B28CFF' })]
      const { wrapper } = await mountAt('/entregas', ranged())
      const ruler = wrapper.get('[data-test="day-ruler"]')
      const marks = ruler.findAll('[data-test="ruler-mark"]')
      expect(marks).toHaveLength(2)
      expect(marks[0]!.element.tagName).toBe('BUTTON')
      expect(marks[0]!.attributes('aria-label')).toBe('10:42 Leitura de markdown')
      expect(marks[0]!.attributes('title')).toBe('10:42 Leitura de markdown')
      expect((marks[0]!.element as HTMLElement).style.backgroundColor).not.toBe('')
      expect((marks[1]!.element as HTMLElement).style.backgroundColor).toBe('')
      expect((marks[0]!.element as HTMLElement).style.left).toBe(`${(42 / 300) * 100}%`)
      expect(ruler.text()).toContain('10h')
      expect(ruler.text()).toContain('15h')
      expect(ruler.element.nextElementSibling).toBe(wrapper.get('[data-test="delivery-timeline"]').element)
    })

    it('o clique rola até o registro e o destaca por 1,5 s', async () => {
      const scrollIntoView = vi.fn()
      Element.prototype.scrollIntoView = scrollIntoView
      const { wrapper } = await mountAt('/entregas', ranged())
      vi.useFakeTimers()
      try {
        await wrapper.findAll('[data-test="ruler-mark"]')[1]!.trigger('click')
        expect(scrollIntoView).toHaveBeenCalledWith(expect.objectContaining({ block: 'nearest', inline: 'nearest' }))
        const target = wrapper.findAll('[data-test="delivery"]').find((d) => d.text().includes('Outra'))!
        expect(target.attributes('data-highlighted')).toBe('true')
        await vi.advanceTimersByTimeAsync(1600)
        expect(wrapper.findAll('[data-test="delivery"]').find((d) => d.text().includes('Outra'))!.attributes('data-highlighted')).toBeUndefined()
      } finally {
        vi.useRealTimers()
        delete (Element.prototype as { scrollIntoView?: unknown }).scrollIntoView
      }
    })

    it('trocar de dia limpa o destaque pendente', async () => {
      Element.prototype.scrollIntoView = vi.fn()
      const y = new Date(); y.setDate(y.getDate() - 1)
      const yd = localDay(y)
      const { wrapper } = await mountAt('/entregas', { ...ranged(), [`GET /api/deliveries?date=${yd}`]: () => jsonResponse(dayOf(yd)) })
      vi.useFakeTimers()
      try {
        await wrapper.findAll('[data-test="ruler-mark"]')[0]!.trigger('click')
        expect(vi.getTimerCount()).toBe(1)
        await wrapper.get('[data-test="prev-day"]').trigger('click')
        await vi.advanceTimersByTimeAsync(0)
        expect(vi.getTimerCount()).toBe(0)
      } finally {
        vi.useRealTimers()
        delete (Element.prototype as { scrollIntoView?: unknown }).scrollIntoView
      }
    })

    it('sem animação quando o sistema pede menos movimento', async () => {
      const scrollIntoView = vi.fn()
      Element.prototype.scrollIntoView = scrollIntoView
      vi.stubGlobal('matchMedia', (q: string) => ({ matches: q.includes('reduce'), media: q, addEventListener() {}, removeEventListener() {} }))
      try {
        const { wrapper } = await mountAt('/entregas', ranged())
        await wrapper.findAll('[data-test="ruler-mark"]')[0]!.trigger('click')
        expect(scrollIntoView).toHaveBeenCalledWith(expect.objectContaining({ behavior: 'auto' }))
      } finally {
        delete (Element.prototype as { scrollIntoView?: unknown }).scrollIntoView
      }
    })
  })

  describe('filtro por projeto', () => {
    const t = Math.floor(Date.now() / 1000)
    const data = () => dayOf(today, {
      deliveries: [
        delivery({ id: 1, finished_at: t - 300, project_id: 1, project_name: 'Loja', summary_title: 'Um' }),
        delivery({ id: 2, finished_at: t - 200, project_id: 2, project_name: 'API', summary_title: 'Dois' }),
        delivery({ id: 3, finished_at: t - 100, project_id: 1, project_name: 'Loja', summary_title: 'Três' }),
      ],
      in_progress: [{ session_id: 'x', project_id: 1, project_name: 'Loja', title: 'Tela', short: null }],
    })
    const routes = () => ({ [`GET /api/deliveries?date=${today}`]: () => jsonResponse(data()) })
    const chip = (wrapper: Awaited<ReturnType<typeof mountAt>>['wrapper'], project: string) => wrapper.get(`[data-test="delivery-filter"][data-project="${project}"]`)

    it('"Todos" com o total e um chip por projeto, na ordem das contagens', async () => {
      useProjectsStore(pinia).projects = [makeProject({ id: 1, name: 'Loja', color: '#B28CFF' })]
      const { wrapper } = await mountAt('/entregas', routes())
      const chips = wrapper.findAll('[data-test="delivery-filter"]')
      expect(chips.map((c) => c.attributes('data-project'))).toEqual(['', 'Loja', 'API'])
      expect(chips.map((c) => c.get('[data-test="filter-chip-count"]').text())).toEqual(['3', '2', '1'])
      expect(chips.map((c) => c.attributes('aria-pressed'))).toEqual(['true', 'false', 'false'])
      expect(chips[0]!.text()).toContain('Todos')
    })

    it('sem entregas não há chips', async () => {
      const { wrapper } = await mountAt('/entregas', { [`GET /api/deliveries?date=${today}`]: () => jsonResponse(dayOf(today)) })
      expect(wrapper.find('[data-test="delivery-filter"]').exists()).toBe(false)
    })

    it('escolher um projeto filtra a linha do tempo e a régua; clicar de novo volta para "Todos"', async () => {
      const { wrapper } = await mountAt('/entregas', routes())
      await chip(wrapper, 'API').trigger('click')
      expect(chip(wrapper, 'API').attributes('aria-pressed')).toBe('true')
      expect(chip(wrapper, '').attributes('aria-pressed')).toBe('false')
      expect(wrapper.findAll('[data-test="delivery"]').map((d) => d.attributes('data-delivery-id'))).toEqual(['2'])
      expect(wrapper.findAll('[data-test="ruler-mark"]')).toHaveLength(1)
      expect(wrapper.get('[data-test="in-progress"]').text()).toContain('Tela')
      await chip(wrapper, 'API').trigger('click')
      expect(wrapper.findAll('[data-test="delivery"]')).toHaveLength(3)
      expect(wrapper.findAll('[data-test="ruler-mark"]')).toHaveLength(3)
      await chip(wrapper, 'Loja').trigger('click')
      await chip(wrapper, '').trigger('click')
      expect(wrapper.findAll('[data-test="delivery"]')).toHaveLength(3)
    })

    it('o filtro é estado da tela e não vai para o endereço', async () => {
      const { wrapper, router } = await mountAt('/entregas', routes())
      await chip(wrapper, 'API').trigger('click')
      expect(router.currentRoute.value.query).toEqual({})
    })

    it('"Copiar o dia" copia só o projeto escolhido', async () => {
      const writeText = vi.fn((_text: string) => Promise.resolve())
      vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } })
      const { wrapper } = await mountAt('/entregas', routes())
      await chip(wrapper, 'API').trigger('click')
      await wrapper.get('[data-test="copy"]').trigger('click')
      await flushPromises()
      expect(writeText).toHaveBeenCalledWith(projectMarkdown(data(), 'API'))
      expect(writeText.mock.calls[0]![0]).not.toContain('Loja')
      expect(wrapper.get('[data-test="copy"]').text()).toBe('Copiado')
      await chip(wrapper, '').trigger('click')
      await wrapper.get('[data-test="copy"]').trigger('click')
      await flushPromises()
      expect(writeText.mock.calls[1]![0]).toContain('Loja')
    })

    it('Shift+C também copia só o projeto escolhido', async () => {
      const writeText = vi.fn((_text: string) => Promise.resolve())
      vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } })
      const { wrapper } = await mountAt('/entregas', routes())
      await chip(wrapper, 'API').trigger('click')
      document.body.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true, key: 'C', shiftKey: true }))
      await flushPromises()
      expect(writeText).toHaveBeenCalledWith(projectMarkdown(data(), 'API'))
    })

    it('trocar de dia sem entrega do projeto escolhido volta para "Todos"', async () => {
      const y = shiftDay(today, -1)
      const { wrapper, router } = await mountAt('/entregas', {
        ...routes(),
        [`GET /api/deliveries?date=${y}`]: () => jsonResponse(dayOf(y, { deliveries: [delivery({ id: 9, project_id: 1, project_name: 'Loja' })] })),
        [`GET /api/deliveries?date=${shiftDay(today, -2)}`]: () => jsonResponse(dayOf(shiftDay(today, -2), { deliveries: [delivery({ id: 10, project_id: 2, project_name: 'API' })] })),
      })
      await chip(wrapper, 'API').trigger('click')
      await router.push({ name: 'deliveries', query: { dia: y } })
      await flushPromises()
      expect(chip(wrapper, '').attributes('aria-pressed')).toBe('true')
      expect(wrapper.findAll('[data-test="delivery"]')).toHaveLength(1)
      // e a escolha antiga não volta sozinha num dia que tenha o projeto
      await router.push({ name: 'deliveries', query: { dia: shiftDay(today, -2) } })
      await flushPromises()
      expect(chip(wrapper, '').attributes('aria-pressed')).toBe('true')
      expect(wrapper.findAll('[data-test="delivery"]')).toHaveLength(1)
    })

    it('trocar de dia com o projeto escolhido presente no dia novo mantém o filtro', async () => {
      const y = shiftDay(today, -1)
      const { wrapper, router } = await mountAt('/entregas', {
        ...routes(),
        [`GET /api/deliveries?date=${y}`]: () => jsonResponse(dayOf(y, { deliveries: [
          delivery({ id: 9, project_id: 1, project_name: 'Loja' }), delivery({ id: 8, project_id: 2, project_name: 'API' }),
        ] })),
      })
      await chip(wrapper, 'API').trigger('click')
      await router.push({ name: 'deliveries', query: { dia: y } })
      await flushPromises()
      expect(chip(wrapper, 'API').attributes('aria-pressed')).toBe('true')
      expect(wrapper.findAll('[data-test="delivery"]').map((d) => d.attributes('data-delivery-id'))).toEqual(['8'])
    })
  })

  describe('copiar uma entrega', () => {
    const rows = () => dayOf(today, {
      deliveries: [
        delivery({ id: 1, summary_title: 'Pronta', bullets: ['a', 'b'] }),
        delivery({ id: 2, status: 'pending', summary_title: null, title: 'Escrevendo', bullets: [] }),
        delivery({ id: 3, status: 'error', summary_title: 'Falhou', bullets: ['x'], error: 'Limite.' }),
      ],
    })

    it('copia o markdown da entrega, marca o visto por 2 s e anuncia', async () => {
      const writeText = vi.fn((_text: string) => Promise.resolve())
      vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } })
      const { wrapper } = await mountAt('/entregas', { [`GET /api/deliveries?date=${today}`]: () => jsonResponse(rows()) })
      const buttons = wrapper.findAll('[data-test="copy-delivery"]')
      expect(buttons).toHaveLength(3)
      expect(buttons[0]!.attributes('aria-label')).toBe('Copiar esta entrega')
      vi.useFakeTimers()
      try {
        await buttons[0]!.trigger('click')
        await vi.advanceTimersByTimeAsync(0)
        expect(writeText).toHaveBeenCalledWith('**Pronta**\n- a\n- b\n')
        expect(wrapper.findAll('[data-test="copy-delivery"]')[0]!.attributes('data-copied')).toBe('true')
        expect(wrapper.findAll('[data-test="copy-delivery"]')[1]!.attributes('data-copied')).toBeUndefined()
        expect(wrapper.get('[data-test="copy-status"]').text()).toBe('Entrega copiada')
        await vi.advanceTimersByTimeAsync(2100)
        expect(wrapper.findAll('[data-test="copy-delivery"]')[0]!.attributes('data-copied')).toBeUndefined()
        expect(wrapper.get('[data-test="copy-status"]').text()).toBe('')
      } finally {
        vi.useRealTimers()
      }
    })

    it('numa entrega pendente ou com erro copia só o título', async () => {
      const writeText = vi.fn((_text: string) => Promise.resolve())
      vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } })
      const { wrapper } = await mountAt('/entregas', { [`GET /api/deliveries?date=${today}`]: () => jsonResponse(rows()) })
      const buttons = wrapper.findAll('[data-test="copy-delivery"]')
      await buttons[1]!.trigger('click')
      await buttons[2]!.trigger('click')
      await flushPromises()
      expect(writeText.mock.calls.map((c) => c[0])).toEqual(['**Escrevendo**\n', '**Falhou**\n'])
    })

    it('copiar a entrega não muda o botão "Copiar o dia" e avisa quando falha', async () => {
      const writeText = vi.fn(() => Promise.reject(new Error('negado')))
      vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } })
      const { wrapper } = await mountAt('/entregas', { [`GET /api/deliveries?date=${today}`]: () => jsonResponse(rows()) })
      await wrapper.findAll('[data-test="copy-delivery"]')[0]!.trigger('click')
      await flushPromises()
      expect(wrapper.get('[role="alert"]').text()).toBe('Não foi possível copiar.')
      expect(wrapper.get('[data-test="copy"]').text()).toBe('Copiar o dia')
      expect(wrapper.findAll('[data-test="copy-delivery"]')[0]!.attributes('data-copied')).toBeUndefined()
    })
  })

  describe('dias e atalhos', () => {
    const yesterday = () => { const d = new Date(); d.setDate(d.getDate() - 1); return localDay(d) }
    const press = (init: KeyboardEventInit, target: Element = document.body) => {
      target.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true, ...init }))
    }

    it('‹ vai para o dia anterior com entregas, ou para o dia anterior comum sem o campo', async () => {
      const far = shiftDay(today, -5)
      const withField = await mountAt('/entregas', { [`GET /api/deliveries?date=${today}`]: () => jsonResponse(dayOf(today, { prev_day: far })) })
      await withField.wrapper.get('[data-test="prev-day"]').trigger('click')
      await flushPromises()
      expect(withField.router.currentRoute.value.query.dia).toBe(far)
      const without = await mountAt('/entregas', { [`GET /api/deliveries?date=${today}`]: () => jsonResponse({ ...dayOf(today), prev_day: undefined }) })
      await without.wrapper.get('[data-test="prev-day"]').trigger('click')
      await flushPromises()
      expect(without.router.currentRoute.value.query.dia).toBe(yesterday())
    })

    it('› vai para o dia seguinte com entregas, sem passar de hoje', async () => {
      const y = yesterday()
      const base = shiftDay(today, -4)
      const routes = {
        [`GET /api/deliveries?date=${base}`]: () => jsonResponse(dayOf(base, { next_day: y })),
        [`GET /api/deliveries?date=${y}`]: () => jsonResponse(dayOf(y)),
        [`GET /api/deliveries?date=${today}`]: () => jsonResponse(dayOf(today)),
      }
      const jump = await mountAt(`/entregas?dia=${base}`, routes)
      await jump.wrapper.get('[data-test="next-day"]').trigger('click')
      await flushPromises()
      expect(jump.router.currentRoute.value.query.dia).toBe(y)
      const past = await mountAt(`/entregas?dia=${base}`, { ...routes, [`GET /api/deliveries?date=${base}`]: () => jsonResponse(dayOf(base, { next_day: shiftDay(today, 3) })) })
      await past.wrapper.get('[data-test="next-day"]').trigger('click')
      await flushPromises()
      expect(past.router.currentRoute.value.query.dia).toBe(shiftDay(base, 1))
      const missing = await mountAt(`/entregas?dia=${base}`, { ...routes, [`GET /api/deliveries?date=${base}`]: () => jsonResponse({ ...dayOf(base), next_day: undefined }) })
      await missing.wrapper.get('[data-test="next-day"]').trigger('click')
      await flushPromises()
      expect(missing.router.currentRoute.value.query.dia).toBe(shiftDay(base, 1))
    })

    it('← e → trocam de dia e → não passa de hoje', async () => {
      const y = yesterday()
      const { router } = await mountAt('/entregas', {
        [`GET /api/deliveries?date=${today}`]: () => jsonResponse(dayOf(today)),
        [`GET /api/deliveries?date=${y}`]: () => jsonResponse(dayOf(y)),
      })
      press({ key: 'ArrowRight' })
      await flushPromises()
      expect(router.currentRoute.value.query.dia).toBeUndefined()
      press({ key: 'ArrowLeft' })
      await flushPromises()
      expect(router.currentRoute.value.query.dia).toBe(y)
      press({ key: 'ArrowRight' })
      await flushPromises()
      expect(router.currentRoute.value.query.dia).toBeUndefined()
    })

    it('Shift+C copia o dia; C sozinho não; campos de texto e dialogs não disparam', async () => {
      const writeText = vi.fn(() => Promise.resolve())
      vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } })
      const { wrapper } = await mountAt('/entregas', {
        [`GET /api/deliveries?date=${today}`]: () => jsonResponse(dayOf(today, { deliveries: [delivery()] })),
      })
      press({ key: 'c' })
      const input = document.body.appendChild(document.createElement('input'))
      press({ key: 'C', shiftKey: true }, input)
      input.remove()
      await flushPromises()
      expect(writeText).not.toHaveBeenCalled()
      const dialog = document.body.appendChild(document.createElement('div'))
      dialog.setAttribute('role', 'dialog')
      press({ key: 'C', shiftKey: true })
      dialog.remove()
      await flushPromises()
      expect(writeText).not.toHaveBeenCalled()
      press({ key: 'C', shiftKey: true })
      await flushPromises()
      expect(writeText).toHaveBeenCalledTimes(1)
      expect(wrapper.get('[data-test="copy"]').text()).toBe('Copiado')
    })

    it('tira os atalhos ao desmontar a tela', async () => {
      const y = yesterday()
      const { wrapper, router } = await mountAt('/entregas', {
        [`GET /api/deliveries?date=${today}`]: () => jsonResponse(dayOf(today)),
        [`GET /api/deliveries?date=${y}`]: () => jsonResponse(dayOf(y)),
      })
      wrapper.unmount()
      press({ key: 'ArrowLeft' })
      await flushPromises()
      expect(router.currentRoute.value.query.dia).toBeUndefined()
    })
  })

  it('ao sair da tela o store deixa de acompanhar o dia, mas guarda o que já leu', async () => {
    const { wrapper } = await mountAt('/entregas', { [`GET /api/deliveries?date=${today}`]: () => jsonResponse(dayOf(today, { deliveries: [delivery()] })) })
    const store = useDeliveriesStore()
    expect(store.date).toBe(today)
    wrapper.unmount()
    expect(store.date).toBeNull()
    expect(store.day?.deliveries).toHaveLength(1)
  })
})

describe('etiquetas nas Entregas', () => {
  it('a linha do tempo e "Em andamento" mostram o projeto, não as etiquetas da conversa', async () => {
    useLabelsStore(pinia).labels = [makeLabel({ id: 1, slug: 'urgente' })]
    useSessionsStore(pinia).setForProject(1, [makeSession({ session_id: 's1', label_ids: [1] }), makeSession({ session_id: 'andamento', label_ids: [1] })])
    const { wrapper } = await mountAt('/entregas', {
      [`GET /api/deliveries?date=${today}`]: () => jsonResponse(dayOf(today, {
        deliveries: [delivery({ id: 1, session_id: 's1' })],
        in_progress: [{ session_id: 'andamento', project_id: 1, project_name: 'app', title: 'Rodando', short: null }],
      })),
    })
    expect(wrapper.find('[data-test="label-badges"]').exists()).toBe(false)
  })
})
