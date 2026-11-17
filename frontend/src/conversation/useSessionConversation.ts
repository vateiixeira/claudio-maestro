import { computed, shallowReactive, shallowRef, toValue, watch, type ComputedRef, type MaybeRefOrGetter } from 'vue'
import { errorMessage } from '../api/http'
import { useEventSocket } from '../api/socket'
import { useConversationStore, type Conversation } from '../stores/conversation'

/** What the users of one session share: the subscriptions, the use count and the state of the load. */
interface Shared {
  users: number
  /** The conversation was in the store before the first use: someone else owns it, so it is not forgotten. */
  preexisting: boolean
  offs: Array<() => void>
  state: { pending: number; error: string | null }
  reload: () => Promise<void>
}

const shared = new Map<string, Shared>()

/**
 * The conversation of a session read for display (the steps of a run inside another conversation). The
 * first use of a session loads it and follows its events; later uses of the same session only read.
 * When the last use leaves, the subscriptions end and the store forgets the conversation, unless it was
 * already there before the first use. A null id does nothing.
 */
export function useSessionConversation(sessionId: MaybeRefOrGetter<string | null>): {
  conv: ComputedRef<Conversation | undefined>
  loading: ComputedRef<boolean>
  error: ComputedRef<string | null>
  reload: () => Promise<void>
} {
  const conversations = useConversationStore()
  const socket = useEventSocket()
  const current = shallowRef<Shared | null>(null)

  function acquire(id: string): Shared {
    const existing = shared.get(id)
    if (existing) {
      existing.users++
      return existing
    }
    const state = shallowReactive({ pending: 0, error: null as string | null })
    const entry: Shared = {
      users: 1,
      preexisting: conversations.get(id) !== undefined,
      offs: [],
      state,
      async reload() {
        state.pending++
        try {
          const loaded = await conversations.load(id)
          if (loaded) state.error = null
        } catch (e) {
          state.error = errorMessage(e)
        } finally {
          state.pending--
        }
      },
    }
    shared.set(id, entry)
    entry.offs = [
      socket.onSession(id, (event) => conversations.receive(event)),
      // Every opening, the first included: events between the snapshot and it were lost.
      socket.onOpen(() => { void entry.reload() }),
    ]
    void entry.reload()
    return entry
  }

  function release(id: string, entry: Shared) {
    entry.users--
    if (entry.users > 0) return
    entry.offs.forEach((off) => off())
    shared.delete(id)
    if (!entry.preexisting) conversations.forget(id)
  }

  watch(
    () => toValue(sessionId),
    // The cleanup also runs when the scope stops, which covers the unmount.
    (id, _before, onCleanup) => {
      if (id === null) {
        current.value = null
        return
      }
      const entry = acquire(id)
      current.value = entry
      onCleanup(() => {
        current.value = null
        release(id, entry)
      })
    },
    { immediate: true },
  )

  return {
    conv: computed(() => {
      const id = toValue(sessionId)
      return id === null ? undefined : conversations.get(id)
    }),
    loading: computed(() => (current.value?.state.pending ?? 0) > 0),
    error: computed(() => current.value?.state.error ?? null),
    reload: async () => { await current.value?.reload() },
  }
}
