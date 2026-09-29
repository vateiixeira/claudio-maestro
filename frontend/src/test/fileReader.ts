import { flushPromises } from '@vue/test-utils'
import { vi } from 'vitest'

// jsdom's FileReader finishes after three chained macrotasks, so a fixed `setTimeout(0)` is not
// enough under load. Tracking each reader until `loadend` makes the wait deterministic.
const pendingReads: Promise<void>[] = []
const RealFileReader = FileReader

class TrackedFileReader extends RealFileReader {
  constructor() {
    super()
    pendingReads.push(new Promise<void>((resolve) => this.addEventListener('loadend', () => resolve())))
  }
}

/** Replaces the global `FileReader` with one that `settleReads` can wait for. Undo with `vi.unstubAllGlobals()`. */
export function trackFileReads() {
  pendingReads.length = 0
  vi.stubGlobal('FileReader', TrackedFileReader)
}

/** Forgets the readers tracked so far. Call it in `afterEach`. */
export function resetFileReads() {
  pendingReads.length = 0
}

/** Waits for every FileReader started so far, then for the component to apply the results. */
export async function settleReads() {
  await flushPromises()
  await Promise.all(pendingReads)
  await flushPromises()
}
