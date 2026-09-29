import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { DEFAULT_WIDTH, MIN_WIDTH, useLayoutStore } from '../layout'
import { jsonResponse, routeFetch } from '../../test/factories'

beforeEach(() => {
  setActivePinia(createPinia())
  vi.useFakeTimers()
})
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

function putCalls(fetchMock: ReturnType<typeof routeFetch>) {
  return fetchMock.mock.calls.filter(([, init]) => init?.method === 'PUT')
}

describe('store de layout', () => {
  it('abrir adiciona a coluna uma vez só, na ordem', () => {
    const layout = useLayoutStore()
    layout.open('a')
    layout.open('b')
    layout.open('a')
    expect(layout.columns).toEqual(['a', 'b'])
    expect(layout.widthOf('a')).toBe(DEFAULT_WIDTH)
  })

  it('fechar remove só aquela coluna', () => {
    const layout = useLayoutStore()
    layout.open('a')
    layout.open('b')
    layout.setWidth('a', 700)
    layout.close('a')
    expect(layout.columns).toEqual(['b'])
    expect(layout.widths.a).toBeUndefined()
  })

  it('a largura respeita o mínimo', () => {
    const layout = useLayoutStore()
    layout.open('a')
    layout.setWidth('a', 100)
    expect(layout.widthOf('a')).toBe(MIN_WIDTH)
    layout.setWidth('a', 812.6)
    expect(layout.widthOf('a')).toBe(813)
  })

  it('restaura do servidor e grava com atraso depois de mudanças', async () => {
    const fetchMock = routeFetch({
      'GET /api/state': () => jsonResponse({ layout: { columns: ['x', 'y'], widths: { x: 600, y: 200 } } }),
      'PUT /api/state/layout': (init) => jsonResponse(JSON.parse(String(init?.body))),
    })
    vi.stubGlobal('fetch', fetchMock)
    const layout = useLayoutStore()
    await layout.restore()
    expect(layout.columns).toEqual(['x', 'y'])
    expect(layout.widthOf('x')).toBe(600)
    expect(layout.widthOf('y')).toBe(MIN_WIDTH)
    await vi.advanceTimersByTimeAsync(1000)
    expect(putCalls(fetchMock)).toHaveLength(0)

    layout.open('z')
    layout.setWidth('z', 400)
    await flushPromises()
    await vi.advanceTimersByTimeAsync(300)
    expect(putCalls(fetchMock)).toHaveLength(0)
    await vi.advanceTimersByTimeAsync(300)
    const puts = putCalls(fetchMock)
    expect(puts).toHaveLength(1)
    expect(JSON.parse(String(puts[0]![1]!.body))).toEqual({
      columns: ['x', 'y', 'z'],
      widths: { x: 600, y: MIN_WIDTH, z: 400 },
    })
  })

  it('não grava antes de restaurar e junta colunas abertas antes disso', async () => {
    let resolveGet!: (r: Response) => void
    const fetchMock = routeFetch({
      'GET /api/state': () => new Promise<Response>((r) => { resolveGet = r }),
      'PUT /api/state/layout': () => jsonResponse({}),
    })
    vi.stubGlobal('fetch', fetchMock)
    const layout = useLayoutStore()
    const done = layout.restore()
    layout.open('novo')
    await vi.advanceTimersByTimeAsync(1000)
    expect(putCalls(fetchMock)).toHaveLength(0)
    resolveGet(jsonResponse({ layout: { columns: ['velho'], widths: {} } }))
    await done
    expect(layout.columns).toEqual(['velho', 'novo'])
    await vi.advanceTimersByTimeAsync(600)
    expect(putCalls(fetchMock)).toHaveLength(1)
  })

  it('ignora layout salvo inválido ou falha ao ler', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/state': () => jsonResponse({ layout: 'lixo' }) }))
    const layout = useLayoutStore()
    await layout.restore()
    expect(layout.columns).toEqual([])
    expect(layout.restored).toBe(true)
  })

  it('se a leitura falhar não grava por cima do layout salvo', async () => {
    const fetchMock = routeFetch({
      'GET /api/state': () => jsonResponse({ detail: 'erro' }, 500),
      'PUT /api/state/layout': () => jsonResponse({}),
    })
    vi.stubGlobal('fetch', fetchMock)
    const layout = useLayoutStore()
    await layout.restore()
    layout.open('a')
    await vi.advanceTimersByTimeAsync(1000)
    expect(putCalls(fetchMock)).toHaveLength(0)
  })

  it('coluna fechada durante a restauração não volta', async () => {
    let resolveGet!: (r: Response) => void
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/state': () => new Promise<Response>((r) => { resolveGet = r }),
      'PUT /api/state/layout': () => jsonResponse({}),
    }))
    const layout = useLayoutStore()
    const done = layout.restore()
    layout.open('velho')
    layout.close('velho')
    resolveGet(jsonResponse({ layout: { columns: ['velho', 'outro'], widths: {} } }))
    await done
    expect(layout.columns).toEqual(['outro'])
  })

  it('lê finished_after_days das preferências, padrão 3', async () => {
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/state': () => jsonResponse({ preferences: { finished_after_days: 7 } }),
    }))
    const layout = useLayoutStore()
    expect(layout.finishedAfterDays).toBe(3)
    await layout.restore()
    expect(layout.finishedAfterDays).toBe(7)
  })
})
