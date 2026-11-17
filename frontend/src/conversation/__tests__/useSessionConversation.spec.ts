import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { defineComponent, h, ref, type Ref } from 'vue'
import { emptyConversation, useConversationStore } from '../../stores/conversation'
import { useSessionConversation } from '../useSessionConversation'

const fake = vi.hoisted(() => ({
  session: new Map<string, Array<(e: unknown) => void>>(),
  open: new Set<() => void>(),
  sessionOffs: 0,
  openOffs: 0,
}))
vi.mock('../../api/socket', () => ({
  useEventSocket: () => ({
    onSession: (id: string, handler: (e: unknown) => void) => {
      fake.session.set(id, [...(fake.session.get(id) ?? []), handler])
      return () => { fake.sessionOffs++ }
    },
    onOpen: (handler: () => void) => {
      fake.open.add(handler)
      return () => { fake.openOffs++; fake.open.delete(handler) }
    },
  }),
}))

enableAutoUnmount(afterEach)
let pinia: Pinia
let store: ReturnType<typeof useConversationStore>
let load: ReturnType<typeof vi.spyOn>
let forget: ReturnType<typeof vi.spyOn>

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  fake.session.clear()
  fake.open.clear()
  fake.sessionOffs = 0
  fake.openOffs = 0
  store = useConversationStore(pinia)
  load = vi.spyOn(store, 'load').mockImplementation(async (id: string) => {
    store.bySession[id] = emptyConversation(id)
    return store.bySession[id]!
  })
  forget = vi.spyOn(store, 'forget')
})

function host(id: Ref<string | null>) {
  let result!: ReturnType<typeof useSessionConversation>
  const Host = defineComponent({
    setup() {
      result = useSessionConversation(id)
      return () => h('div')
    },
  })
  const wrapper = mount(Host, { global: { plugins: [pinia] } })
  return { wrapper, get api() { return result } }
}

describe('useSessionConversation', () => {
  it('loads and subscribes once for two uses of the same session', async () => {
    const a = host(ref('s1'))
    const b = host(ref('s1'))
    await flushPromises()
    expect(load).toHaveBeenCalledTimes(1)
    expect(fake.session.get('s1')).toHaveLength(1)
    expect(fake.open.size).toBe(1)
    expect(a.api.conv.value?.sessionId).toBe('s1')
    expect(b.api.conv.value?.sessionId).toBe('s1')
  })

  it('forgets the session only when the last use leaves', async () => {
    const a = host(ref('s1'))
    const b = host(ref('s1'))
    await flushPromises()
    a.wrapper.unmount()
    expect(forget).not.toHaveBeenCalled()
    expect(fake.sessionOffs).toBe(0)
    b.wrapper.unmount()
    expect(forget).toHaveBeenCalledWith('s1')
    expect(fake.sessionOffs).toBe(1)
    expect(fake.openOffs).toBe(1)
  })

  it('does not forget a conversation that was already in the store', async () => {
    store.bySession.s1 = emptyConversation('s1')
    const a = host(ref('s1'))
    await flushPromises()
    a.wrapper.unmount()
    expect(forget).not.toHaveBeenCalled()
    expect(fake.sessionOffs).toBe(1)
  })

  it('does nothing for a null id', async () => {
    const a = host(ref(null))
    await flushPromises()
    expect(load).not.toHaveBeenCalled()
    expect(fake.session.size).toBe(0)
    expect(a.api.conv.value).toBeUndefined()
    a.wrapper.unmount()
    expect(forget).not.toHaveBeenCalled()
  })

  it('moves to the new session when the id changes', async () => {
    const id = ref<string | null>('s1')
    const a = host(id)
    await flushPromises()
    id.value = 's2'
    await flushPromises()
    expect(forget).toHaveBeenCalledWith('s1')
    expect(load).toHaveBeenCalledWith('s2')
    expect(a.api.conv.value?.sessionId).toBe('s2')
  })

  it('reloads when the socket opens', async () => {
    host(ref('s1'))
    await flushPromises()
    fake.open.forEach((handler) => handler())
    await flushPromises()
    expect(load).toHaveBeenCalledTimes(2)
  })

  it('shows the error of a failed load and retries with reload', async () => {
    load.mockReset()
    load.mockRejectedValueOnce(new Error('falhou'))
    load.mockImplementation(async (id: string) => {
      store.bySession[id] = emptyConversation(id)
      return store.bySession[id]!
    })
    const a = host(ref('s1'))
    await flushPromises()
    expect(a.api.error.value).toBe('falhou')
    expect(a.api.loading.value).toBe(false)
    await a.api.reload()
    expect(load).toHaveBeenCalledTimes(2)
    expect(a.api.error.value).toBeNull()
    expect(a.api.conv.value).toBeDefined()
  })
})
