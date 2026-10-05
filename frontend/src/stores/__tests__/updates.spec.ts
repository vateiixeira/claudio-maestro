import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import type { UpdateState } from '../../types/api'

const getUpdates = vi.hoisted(() => vi.fn())
vi.mock('../../api/http', () => ({ getUpdates }))

import { useUpdatesStore } from '../updates'

function makeState(overrides: Partial<UpdateState> = {}): UpdateState {
  return {
    enabled: true,
    current: '0.1.0',
    available: true,
    latest: { version: '0.2.0', url: 'https://github.com/vateiixeira/claudio-maestro/releases/tag/v0.2.0', notes: '- coisa', published_at: 1791288000 },
    checked_at: 1791303600,
    releases_url: 'https://github.com/vateiixeira/claudio-maestro/releases',
    ...overrides,
  }
}

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.removeItem('maestro:update-dismissed')
  getUpdates.mockReset()
})
afterEach(() => vi.restoreAllMocks())

describe('store de versão', () => {
  it('carrega o estado e mostra o aviso quando há versão nova', async () => {
    getUpdates.mockResolvedValue(makeState())
    const store = useUpdatesStore()
    await store.load()
    expect(store.state?.current).toBe('0.1.0')
    expect(store.showNotice).toBe(true)
  })

  it('não mostra o aviso com versão igual, sem release ou desligado', () => {
    const store = useUpdatesStore()
    store.apply(makeState({ available: false }))
    expect(store.showNotice).toBe(false)
    store.apply(makeState({ latest: null, available: false }))
    expect(store.showNotice).toBe(false)
    store.apply(makeState({ enabled: false }))
    expect(store.showNotice).toBe(false)
  })

  it('dispensar esconde só aquela versão e fica guardado', () => {
    const store = useUpdatesStore()
    store.apply(makeState())
    store.openModal()
    store.dismiss()
    expect(store.showNotice).toBe(false)
    expect(store.modalOpen).toBe(false)
    expect(localStorage.getItem('maestro:update-dismissed')).toBe('0.2.0')

    setActivePinia(createPinia())
    const again = useUpdatesStore()
    again.apply(makeState())
    expect(again.showNotice).toBe(false)
    again.apply(makeState({ latest: { ...makeState().latest!, version: '0.3.0' } }))
    expect(again.showNotice).toBe(true)
  })

  it('funciona quando o localStorage lança exceção', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('bloqueado') })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('bloqueado') })
    const store = useUpdatesStore()
    store.apply(makeState())
    expect(store.showNotice).toBe(true)
    store.dismiss()
    expect(store.showNotice).toBe(false)
  })

  it('o evento app.update troca o estado e ignora dados inválidos', () => {
    const store = useUpdatesStore()
    store.apply(makeState())
    store.apply({ nada: 1 })
    store.apply(null)
    expect(store.state?.latest?.version).toBe('0.2.0')
  })

  it('ignora resposta do load que chegou depois de um evento', async () => {
    let resolve!: (value: UpdateState) => void
    getUpdates.mockReturnValue(new Promise<UpdateState>((r) => { resolve = r }))
    const store = useUpdatesStore()
    const pending = store.load()
    store.apply(makeState({ latest: { ...makeState().latest!, version: '0.3.0' } }))
    resolve(makeState())
    await pending
    expect(store.state?.latest?.version).toBe('0.3.0')
  })

  it('openModal só abre quando há release', () => {
    const store = useUpdatesStore()
    store.openModal()
    expect(store.modalOpen).toBe(false)
    store.apply(makeState())
    store.openModal()
    expect(store.modalOpen).toBe(true)
    store.closeModal()
    expect(store.modalOpen).toBe(false)
  })
})
