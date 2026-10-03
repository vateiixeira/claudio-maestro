import { onScopeDispose, ref, toValue, watch, type MaybeRefOrGetter, type Ref } from 'vue'
import { useMediaQuery } from '../useMediaQuery'

/** Slowest release rate, in characters per second. */
const MIN_RATE = 90
/** Whatever is still waiting is released in about this many seconds. */
const CATCH_UP_SECONDS = 0.4

/**
 * Text to show for a reply whose chunks arrive in bursts: while `streaming` (and until the
 * text that arrived has been fully shown) it releases characters on animation frames at a
 * steady `max(90, delay / 0.4)` characters per second. Without streaming (history, reload)
 * or with `prefers-reduced-motion`, it is the text that arrived, at once.
 */
export function useSmoothText(
  text: MaybeRefOrGetter<string>,
  streaming: MaybeRefOrGetter<boolean>,
): Ref<string> {
  const reduced = useMediaQuery('(prefers-reduced-motion: reduce)')
  const initial = toValue(text)
  const shown = ref(initial)
  // Float position in the text; text present at mount is shown whole, only what arrives later is paced.
  let pos = initial.length
  // True from the first streaming moment until the released text has caught up with what arrived.
  let active = toValue(streaming)
  let frame: number | null = null
  let last: number | null = null

  function show(full: string, length: number) {
    let n = Math.min(Math.floor(length), full.length)
    // Never cut a surrogate pair in half.
    if (n > 0 && n < full.length) {
      const code = full.charCodeAt(n - 1)
      if (code >= 0xd800 && code <= 0xdbff) n -= 1
    }
    const next = full.slice(0, n)
    if (next !== shown.value) shown.value = next
  }

  function stopFrames() {
    if (frame !== null) cancelAnimationFrame(frame)
    frame = null
    last = null
  }

  function step(timestamp: number) {
    frame = null
    const full = toValue(text)
    const dt = last === null ? 0 : Math.max(0, (timestamp - last) / 1000)
    last = timestamp
    const delay = full.length - pos
    const rate = Math.max(MIN_RATE, delay / CATCH_UP_SECONDS)
    pos = Math.min(full.length, pos + rate * dt)
    show(full, pos)
    if (pos >= full.length) {
      last = null
      if (!toValue(streaming)) active = false
      return
    }
    frame = requestAnimationFrame(step)
  }

  function sync() {
    const full = toValue(text)
    if (reduced.value) {
      stopFrames()
      active = false
      pos = full.length
      show(full, pos)
      return
    }
    if (toValue(streaming)) active = true
    if (!active) {
      stopFrames()
      pos = full.length
      show(full, pos)
      return
    }
    // The final text is not a continuation of what was shown (rewritten or shrunk) and no more
    // is coming: show it whole instead of replaying it.
    if (!toValue(streaming) && !full.startsWith(shown.value)) {
      stopFrames()
      active = false
      pos = full.length
      show(full, pos)
      return
    }
    if (pos > full.length) pos = full.length
    if (pos < full.length) {
      show(full, pos)
      if (frame === null) frame = requestAnimationFrame(step)
    } else {
      stopFrames()
      show(full, pos)
      if (!toValue(streaming)) active = false
    }
  }

  watch([() => toValue(text), () => toValue(streaming), reduced], sync)
  onScopeDispose(stopFrames)
  return shown
}
