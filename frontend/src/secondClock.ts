import { onScopeDispose, ref, toValue, watch, type MaybeRefOrGetter, type Ref } from 'vue'

/** Now, in ms, refreshed every second while anyone asks for it; one timer for the whole app. */
const now = ref(Date.now())
let users = 0
let timer: ReturnType<typeof setInterval> | null = null

function start() {
  now.value = Date.now()
  timer = setInterval(() => { now.value = Date.now() }, 1000)
}

function stop() {
  if (timer) clearInterval(timer)
  timer = null
}

/**
 * The shared clock of the running times. It only ticks while at least one caller has `active` true,
 * so nothing wakes up every second for a conversation with nothing running in view. Call it inside a
 * component's `setup`: leaving it releases the caller's hold.
 */
export function useSecondClock(active: MaybeRefOrGetter<boolean>): Ref<number> {
  let held = false
  const hold = (on: boolean) => {
    if (on === held) return
    held = on
    users += on ? 1 : -1
    if (on && users === 1) start()
    else if (!on && users === 0) stop()
  }
  watch(() => toValue(active), hold, { immediate: true, flush: 'sync' })
  onScopeDispose(() => hold(false))
  return now
}
