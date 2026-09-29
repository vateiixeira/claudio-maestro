import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { DEFAULT_FINISHED_AFTER_DAYS, useLayoutStore } from '../layout'
import { jsonResponse, routeFetch } from '../../test/factories'

beforeEach(() => {
  setActivePinia(createPinia())
})
afterEach(() => {
  vi.unstubAllGlobals()
})

describe('store de preferências', () => {
  it('lê os dias para finalizar das preferências', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/state': () => jsonResponse({ preferences: { finished_after_days: 5 } }) }))
    const layout = useLayoutStore()
    expect(layout.finishedAfterDays).toBe(DEFAULT_FINISHED_AFTER_DAYS)
    await layout.restore()
    expect(layout.finishedAfterDays).toBe(5)
    expect(layout.loadedFromServer).toBe(true)
    expect(layout.restored).toBe(true)
  })

  it('valor inválido mantém o padrão', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/state': () => jsonResponse({ preferences: { finished_after_days: -2 } }) }))
    const layout = useLayoutStore()
    await layout.restore()
    expect(layout.finishedAfterDays).toBe(DEFAULT_FINISHED_AFTER_DAYS)
  })

  it('não grava nada no estado do app', async () => {
    const fetch = routeFetch({ 'GET /api/state': () => jsonResponse({}) })
    vi.stubGlobal('fetch', fetch)
    await useLayoutStore().restore()
    await new Promise((r) => setTimeout(r, 600))
    expect(fetch.mock.calls.every(([, init]) => (init?.method ?? 'GET') === 'GET')).toBe(true)
  })

  it('só expõe as preferências', () => {
    const layout = useLayoutStore()
    expect('columns' in layout).toBe(false)
    expect('setWidth' in layout).toBe(false)
  })

  it('duas leituras ao mesmo tempo fazem uma requisição só', async () => {
    let gets = 0
    let resolveGet!: (r: Response) => void
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/state': () => { gets += 1; return new Promise<Response>((r) => { resolveGet = r }) },
    }))
    const layout = useLayoutStore()
    const first = layout.restore()
    const second = layout.restore()
    resolveGet(jsonResponse({ preferences: { finished_after_days: 9 } }))
    await Promise.all([first, second])
    expect(gets).toBe(1)
    expect(layout.finishedAfterDays).toBe(9)
  })

  it('se a leitura falhar mantém o padrão e tenta de novo depois', async () => {
    let fail = true
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/state': () => (fail ? jsonResponse({ detail: 'erro' }, 500) : jsonResponse({ preferences: { finished_after_days: 8 } })),
    }))
    const layout = useLayoutStore()
    await layout.restore()
    expect(layout.restored).toBe(true)
    expect(layout.loadedFromServer).toBe(false)
    expect(layout.finishedAfterDays).toBe(DEFAULT_FINISHED_AFTER_DAYS)
    fail = false
    await layout.restore()
    expect(layout.loadedFromServer).toBe(true)
    expect(layout.finishedAfterDays).toBe(8)
  })
})
