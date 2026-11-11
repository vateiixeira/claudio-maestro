import { computed, ref, watch } from 'vue'

/** Expansion is a reading preference, independent of refreshed Git state. */
export function useRepoExpansion(projectId: () => number, repoPath: () => string, section: 'scm' | 'commits', defaultOpen: () => boolean) {
  const key = computed(() => `maestro:git-expansion:${JSON.stringify([projectId(), repoPath(), section])}`)
  function read(): boolean | null {
    try {
      const value = localStorage.getItem(key.value)
      return value === 'true' ? true : value === 'false' ? false : null
    } catch { return null }
  }
  const saved = read()
  let chosen = saved !== null
  let restoring = false
  const open = ref(saved ?? defaultOpen())
  watch(open, (value) => {
    if (restoring) return
    chosen = true
    try { localStorage.setItem(key.value, String(value)) } catch { /* Storage may be disabled. */ }
  }, { flush: 'sync' })
  watch(key, () => {
    const saved = read()
    chosen = saved !== null
    restoring = true
    open.value = saved ?? defaultOpen()
    restoring = false
  }, { flush: 'sync' })
  watch(defaultOpen, (value) => {
    // A newly relevant repository may open; becoming clean must not collapse a reader.
    if (chosen || !value) return
    restoring = true
    open.value = value
    restoring = false
  }, { flush: 'sync' })
  return open
}
