import { beforeEach, describe, expect, it, vi, afterEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useDeliveriesStore } from '../deliveries'
import { jsonResponse, routeFetch } from '../../test/factories'
import type { DeliveriesDay, Delivery } from '../../types/api'

const at = (h: number) => Math.floor(new Date(2026, 9, 7, h).getTime() / 1000)
function delivery(over: Partial<Delivery> = {}): Delivery {
  return { id: 1, session_id: 's1', project_id: 1, project_name: 'app', title: 'T', finished_at: at(10),
    status: 'pending', summary_title: null, bullets: [], error: null, ...over }
}
const day = (deliveries: Delivery[]): DeliveriesDay => ({ date: '2026-10-07', agent_enabled: true, deliveries, in_progress: [] })

beforeEach(() => setActivePinia(createPinia()))
afterEach(() => vi.unstubAllGlobals())

describe('deliveries store', () => {
  it('carrega um dia', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/deliveries?date=2026-10-07': () => jsonResponse(day([delivery()])) }))
    const store = useDeliveriesStore()
    await store.load('2026-10-07')
    expect(store.day?.deliveries).toHaveLength(1)
    expect(store.error).toBeNull()
  })

  it('guarda a mensagem de erro', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/deliveries?date=2026-10-07': () => jsonResponse({ detail: 'Data inválida.' }, 422) }))
    const store = useDeliveriesStore()
    await store.load('2026-10-07')
    expect(store.error).toBe('Data inválida.')
  })

  it('troca o registro conhecido quando chega o evento', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/deliveries?date=2026-10-07': () => jsonResponse(day([delivery()])) }))
    const store = useDeliveriesStore()
    await store.load('2026-10-07')
    store.applyEvent(delivery({ status: 'done', summary_title: 'Feito', bullets: ['a'] }))
    expect(store.day?.deliveries[0]?.summary_title).toBe('Feito')
  })

  it('recarrega quando chega um registro novo do dia exibido e ignora outros dias', async () => {
    const fetch = routeFetch({ 'GET /api/deliveries?date=2026-10-07': () => jsonResponse(day([])) })
    vi.stubGlobal('fetch', fetch)
    const store = useDeliveriesStore()
    await store.load('2026-10-07')
    store.applyEvent(delivery({ id: 9, finished_at: at(12) - 86400 }))
    store.applyEvent(delivery({ id: 9 }))
    await vi.waitFor(() => expect(fetch).toHaveBeenCalledTimes(2))
  })

  it('pede o resumo de novo e guarda o erro da ação', async () => {
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/deliveries?date=2026-10-07': () => jsonResponse(day([delivery({ status: 'error', error: 'x' })])),
      'POST /api/deliveries/1/summarize': () => jsonResponse({ detail: 'O agente de resumos está desligado.' }, 409),
    }))
    const store = useDeliveriesStore()
    await store.load('2026-10-07')
    await store.summarize(1)
    expect(store.actionErrors[1]).toBe('O agente de resumos está desligado.')
  })
})
