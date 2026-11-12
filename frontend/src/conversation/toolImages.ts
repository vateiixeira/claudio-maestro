import { onBeforeUnmount, ref, watch, type Ref } from 'vue'
import { ApiError, fetchToolImage } from '../api/http'
import type { ToolItem } from '../types/conversation'
import { toolImageRef, toolLabel, str, type ToolImageRef } from './tool'

export { RENDERABLE_IMAGE_TYPES, toolImageRef, type ToolImageRef } from './tool'

// Images a tool returned (a `Read` of a PNG, a screenshot by MCP). The history and the live stream
// carry only a marker; the bytes come from the backend when the screen asks for them.

export interface ToolImageEntry {
  item: ToolItem
  image: ToolImageRef
}

export function toolImagesOf(item: ToolItem): ToolImageRef[] {
  const content = item.result?.content
  if (!Array.isArray(content)) return []
  return content.map(toolImageRef).filter((ref): ref is ToolImageRef => ref !== null)
}

/** The images of several actions in order (the actions, then each one's index). */
export function toolImageEntries(items: readonly ToolItem[]): ToolImageEntry[] {
  return items.flatMap((item) => toolImagesOf(item).map((image) => ({ item, image })))
}

const RETRY_DELAYS_MS = [1000, 2000, 4000]

const urls = new Map<string, string>()
const inflight = new Map<string, Promise<string>>()
const keyOf = (sessionId: string, toolUseId: string, index: number) => `${sessionId}\u0000${toolUseId}\u0000${index}`
const sessionOf = (key: string) => key.slice(0, key.indexOf('\u0000'))

const wait = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms))

// `active` also stops the loop once the request was forgotten (`forgetToolImages`), so it does not keep retrying for nobody.
async function fetchWithRetry(sessionId: string, toolUseId: string, index: number, active: () => boolean): Promise<Blob> {
  for (let attempt = 0; ; attempt++) {
    try {
      return await fetchToolImage(sessionId, toolUseId, index)
    } catch (error) {
      // Live, the CLI may write the line a moment after the event: a 404 is worth another try, only while the session runs.
      const delay = RETRY_DELAYS_MS[attempt]
      if (!(error instanceof ApiError) || error.status !== 404 || delay === undefined || !active()) throw error
      await wait(delay)
      if (!active()) throw error
    }
  }
}

/**
 * An object URL for the image. One fetch per image, shared by the thumbnail and the viewer; a failure is not kept,
 * so opening again tries again. `active` says whether the session is still running (it gates the 404 retries).
 */
export function loadToolImage(sessionId: string, toolUseId: string, index: number, active: () => boolean): Promise<string> {
  const key = keyOf(sessionId, toolUseId, index)
  const cached = urls.get(key)
  if (cached) return Promise.resolve(cached)
  const pending = inflight.get(key)
  if (pending) return pending
  // Still the request of record: `forgetToolImages` (or a newer request for the key) takes it out of `inflight`.
  // Before `inflight.set` below it is still undefined (a synchronous failure), so that counts as alive.
  let promise: Promise<string> | undefined
  const alive = () => promise === undefined || inflight.get(key) === promise
  const current: Promise<string> = fetchWithRetry(sessionId, toolUseId, index, () => active() && alive()).then((blob) => {
    const url = URL.createObjectURL(blob)
    // Forgotten while it loaded (the column closed): do not keep it.
    if (inflight.get(key) !== current) {
      URL.revokeObjectURL(url)
      return url
    }
    inflight.delete(key)
    urls.set(key, url)
    return url
  }, (error) => {
    if (inflight.get(key) === current) inflight.delete(key)
    throw error
  })
  promise = current
  inflight.set(key, promise)
  return current
}

/** Drops the images of a session, when its column closes. */
export function forgetToolImages(sessionId: string): void {
  for (const [key, url] of urls) {
    if (sessionOf(key) !== sessionId) continue
    URL.revokeObjectURL(url)
    urls.delete(key)
  }
  for (const key of [...inflight.keys()]) if (sessionOf(key) === sessionId) inflight.delete(key)
}

export function resetToolImages(): void {
  for (const url of urls.values()) URL.revokeObjectURL(url)
  urls.clear()
  inflight.clear()
}

export type ToolImageState = 'idle' | 'loading' | 'ready' | 'error'

/**
 * Loads the image of `entry` once `enabled` is true (a thumbnail waits until it is on screen) and follows `entry`
 * when it changes (the viewer moving between images).
 */
export function useToolImage(
  sessionId: () => string | null,
  entry: () => ToolImageEntry | null,
  active: () => boolean,
  enabled: Ref<boolean> | (() => boolean) = () => true,
): { url: Ref<string | null>; state: Ref<ToolImageState> } {
  const url = ref<string | null>(null)
  const state = ref<ToolImageState>('idle')
  let current = 0
  let alive = true
  onBeforeUnmount(() => { alive = false })
  watch(
    () => [sessionId(), entry()?.item.tool_use_id, entry()?.image.index, typeof enabled === 'function' ? enabled() : enabled.value] as const,
    ([id, toolUseId, index, on]) => {
      const ticket = ++current
      url.value = null
      if (!id || toolUseId === undefined || index === undefined || !on) {
        state.value = 'idle'
        return
      }
      state.value = 'loading'
      loadToolImage(id, toolUseId, index, active).then(
        (loaded) => { if (alive && ticket === current) { url.value = loaded; state.value = 'ready' } },
        () => { if (alive && ticket === current) state.value = 'error' },
      )
    },
    { immediate: true },
  )
  return { url, state }
}

/** The action an image came from, for the viewer's caption: "Read · tela.png", "playwright · browser_take_screenshot". */
export function imageCaption(item: ToolItem): string {
  const input = item.input ?? {}
  const file = (str(input.file_path) || str(input.filename) || str(input.path)).split(/[\\/]/).pop() ?? ''
  return file ? `${toolLabel(item.name)} · ${file}` : toolLabel(item.name)
}
