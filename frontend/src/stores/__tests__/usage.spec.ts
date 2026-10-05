import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import type { UsageSnapshot } from '../../types/api'

const getUsage = vi.hoisted(() => vi.fn())
vi.mock('../../api/http', () => ({ getUsage }))

import { useUsageStore } from '../usage'

function makeSnapshot(overrides: Partial<UsageSnapshot> = {}): UsageSnapshot {
  return {
    enabled: true,
    limits: [
      { kind: 'session', label: 'Sessão', percent: 14, severity: 'normal', resets_at: 1791333000 },
      { kind: 'weekly_all', label: 'Semana', percent: 17, severity: 'warning', resets_at: 1791237600 },
      { kind: 'weekly_scoped', label: 'Semana · Fable', percent: 3, severity: 'normal', resets_at: 1791237600 },
    ],
    fetched_at: 1791329000,
    error: null,
    plan: 'Max 20x',
    ...overrides,
  }
}

beforeEach(() => {
  setActivePinia(createPinia())
  getUsage.mockReset()
})
afterEach(() => vi.restoreAllMocks())

describe('store de consumo', () => {
  it('carrega o snapshot e separa sessão, semana e por modelo', async () => {
    getUsage.mockResolvedValue(makeSnapshot())
    const store = useUsageStore()
    await store.load()
    expect(store.session?.percent).toBe(14)
    expect(store.weekly?.severity).toBe('warning')
    expect(store.scoped.map((l) => l.label)).toEqual(['Semana · Fable'])
  })

  it('sem snapshot, os atalhos ficam vazios', () => {
    const store = useUsageStore()
    expect(store.session).toBeNull()
    expect(store.weekly).toBeNull()
    expect(store.scoped).toEqual([])
  })

  it('aplica o evento e ignora dados inválidos', () => {
    const store = useUsageStore()
    store.apply(makeSnapshot())
    store.apply({ enabled: 'sim' })
    store.apply(null)
    expect(store.snapshot?.limits).toHaveLength(3)
  })

  it('um GET lento não sobrescreve um evento mais novo', async () => {
    let resolve!: (value: UsageSnapshot) => void
    getUsage.mockReturnValue(new Promise<UsageSnapshot>((r) => { resolve = r }))
    const store = useUsageStore()
    const loading = store.load()
    store.apply(makeSnapshot({ error: 'Login do CLI expirado' }))
    resolve(makeSnapshot())
    await loading
    expect(store.snapshot?.error).toBe('Login do CLI expirado')
  })

  it('uma falha no GET mantém o snapshot anterior', async () => {
    const store = useUsageStore()
    store.apply(makeSnapshot())
    getUsage.mockRejectedValue(new Error('rede'))
    await expect(store.load()).rejects.toThrow('rede')
    expect(store.snapshot?.limits).toHaveLength(3)
  })
})
