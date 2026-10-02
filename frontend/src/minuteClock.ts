import { ref, type Ref } from 'vue'

/** Now, in ms, refreshed every 30 s for relative times; one timer for the whole app. */
export const clockNow = ref(Date.now())
let timer: ReturnType<typeof setInterval> | null = null

export function useMinuteClock(): Ref<number> {
  if (!timer) timer = setInterval(() => { clockNow.value = Date.now() }, 30_000)
  return clockNow
}
