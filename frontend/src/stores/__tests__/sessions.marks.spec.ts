import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import * as http from '../../api/http'
import { useSessionsStore } from '../sessions'
import { makeSession } from '../../test/factories'

beforeEach(() => setActivePinia(createPinia()))

describe('ações de marcação da store', () => {
  it('setMark envia a marcação e os extras, e aplica a resposta', async () => {
    const updated = makeSession({ session_id: 's1', mark: 'on_hold', mark_until: 100 })
    const spy = vi.spyOn(http, 'updateSession').mockResolvedValue(updated)
    const store = useSessionsStore()
    store.setForProject(1, [makeSession({ session_id: 's1' })])
    await store.setMark('s1', 'on_hold', { mark_until: 100 })
    expect(spy).toHaveBeenCalledWith('s1', { mark: 'on_hold', mark_until: 100 })
    expect(store.find('s1')?.mark).toBe('on_hold')
  })
  it('setPriority envia priority', async () => {
    const spy = vi.spyOn(http, 'updateSession').mockResolvedValue(makeSession({ priority: true }))
    await useSessionsStore().setPriority('s1', true)
    expect(spy).toHaveBeenCalledWith('s1', { priority: true })
  })
})
