import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../../api/http', async (orig) => ({
  ...(await orig<typeof import('../../api/http')>()),
  getSessionClosure: vi.fn(),
  resolveClosureItem: vi.fn(),
}))

import { ApiError, getSessionClosure, resolveClosureItem } from '../../api/http'
import { useClosureStore } from '../closure'

const base = { session_id: 's1', verdict: 'user_action', user_actions: ['Reiniciar'], missing: [], evidence: 'e', checked_at: 10, error: null, error_at: null } as const

describe('closure store', () => {
  beforeEach(() => { setActivePinia(createPinia()); vi.resetAllMocks() })

  it('loads and applies events', async () => {
    vi.mocked(getSessionClosure).mockResolvedValue({ ...base, user_actions: [...base.user_actions], missing: [] })
    const store = useClosureStore()
    await store.load('s1')
    expect(store.closures.s1?.verdict).toBe('user_action')
    store.applyClosure({ session_id: 's1', closure: { ...base, verdict: 'can_close', user_actions: [], missing: [] } })
    expect(store.closures.s1?.verdict).toBe('can_close')
  })

  it('resolve replaces the closure', async () => {
    vi.mocked(resolveClosureItem).mockResolvedValue({ ...base, verdict: 'can_close', user_actions: [], missing: [] })
    const store = useClosureStore()
    await store.resolve('s1', 'Reiniciar')
    expect(resolveClosureItem).toHaveBeenCalledWith('s1', 'Reiniciar')
    expect(store.closures.s1?.verdict).toBe('can_close')
    expect(store.busy.s1).toBeNull()
  })

  it('a vanished item reloads and shows the message', async () => {
    vi.mocked(resolveClosureItem).mockRejectedValue(new ApiError(404, 'Item não encontrado; a verificação foi atualizada.', 'Falhou'))
    vi.mocked(getSessionClosure).mockResolvedValue(null)
    const store = useClosureStore()
    await store.resolve('s1', 'Reiniciar')
    expect(getSessionClosure).toHaveBeenCalledWith('s1')
    expect(store.errors.s1).toBe('Item não encontrado; a verificação foi atualizada.')
  })

  it('invalidate clears loaded closures and bumps the epoch', async () => {
    vi.mocked(getSessionClosure).mockResolvedValue({ ...base, user_actions: [], missing: [] })
    const store = useClosureStore()
    await store.load('s1')
    store.invalidate()
    expect('s1' in store.closures).toBe(false)
    expect(store.epoch).toBe(1)
  })

  it('a load in flight does not overwrite a newer event', async () => {
    let release!: (value: null) => void
    vi.mocked(getSessionClosure).mockReturnValue(new Promise((r) => { release = r }))
    const store = useClosureStore()
    const pending = store.load('s1')
    store.applyClosure({ session_id: 's1', closure: { ...base, verdict: 'can_close', user_actions: [], missing: [] } })
    release(null)
    await pending
    expect(store.closures.s1?.verdict).toBe('can_close')
  })
})
