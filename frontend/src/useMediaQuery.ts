import { onBeforeUnmount, ref, type Ref } from 'vue'

/** Reactive `matchMedia(query).matches`; false where matchMedia does not exist. */
export function useMediaQuery(query: string): Ref<boolean> {
  const list = typeof window.matchMedia === 'function' ? window.matchMedia(query) : null
  const matches = ref(list?.matches ?? false)
  const update = (event: { matches: boolean }) => { matches.value = event.matches }
  list?.addEventListener?.('change', update)
  onBeforeUnmount(() => list?.removeEventListener?.('change', update))
  return matches
}
