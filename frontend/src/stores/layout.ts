import { defineStore } from 'pinia'
import { ref, watch } from 'vue'
import * as api from '../api/http'

export const MIN_WIDTH = 360
export const MAX_WIDTH = 2400
export const DEFAULT_WIDTH = 520
export const SAVE_DELAY = 500
export const DEFAULT_FINISHED_AFTER_DAYS = 3

/** What is stored under `layout` in the backend app state. */
export interface SavedLayout {
  columns: string[]
  widths: Record<string, number>
}

function clampWidth(width: number): number {
  return Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, Math.round(width)))
}

function parseLayout(value: unknown): SavedLayout | null {
  if (!value || typeof value !== 'object') return null
  const v = value as Record<string, unknown>
  if (!Array.isArray(v.columns)) return null
  const columns = [...new Set(v.columns.filter((c): c is string => typeof c === 'string' && c !== ''))]
  const widths: Record<string, number> = {}
  if (v.widths && typeof v.widths === 'object') {
    for (const [id, w] of Object.entries(v.widths as Record<string, unknown>)) {
      if (typeof w === 'number' && Number.isFinite(w)) widths[id] = clampWidth(w)
    }
  }
  return { columns, widths }
}

/**
 * Session columns open in the workspace, in order, and their widths. Restored from
 * `GET /api/state` at startup and saved with `PUT /api/state/layout` a moment after
 * each change. Nothing is saved before the restore finishes, so an early change
 * cannot overwrite the saved layout.
 */
export const useLayoutStore = defineStore('layout', () => {
  const columns = ref<string[]>([])
  const widths = ref<Record<string, number>>({})
  const restored = ref(false)
  // `preferences.finished_after_days`: days without activity before a session is finished.
  const finishedAfterDays = ref(DEFAULT_FINISHED_AFTER_DAYS)
  // Saving starts only after the saved layout was read, so a failed read never
  // overwrites it. Columns closed while reading stay closed.
  let canSave = false
  let restoring = false
  const closedMeanwhile = new Set<string>()

  function widthOf(id: string): number {
    return widths.value[id] ?? DEFAULT_WIDTH
  }

  function isOpen(id: string): boolean {
    return columns.value.includes(id)
  }

  function open(id: string): void {
    if (!isOpen(id)) columns.value.push(id)
    closedMeanwhile.delete(id)
  }

  function close(id: string): void {
    columns.value = columns.value.filter((c) => c !== id)
    delete widths.value[id]
    if (restoring) closedMeanwhile.add(id)
  }

  function setWidth(id: string, width: number): void {
    widths.value[id] = clampWidth(width)
  }

  async function restore(): Promise<void> {
    restoring = true
    closedMeanwhile.clear()
    try {
      const state = await api.getAppState()
      const saved = parseLayout(state?.layout)
      const days = (state?.preferences as Record<string, unknown> | undefined)?.finished_after_days
      if (typeof days === 'number' && Number.isFinite(days) && days > 0) finishedAfterDays.value = days
      canSave = true
      if (saved) {
        saved.columns = saved.columns.filter((c) => !closedMeanwhile.has(c))
        const openedMeanwhile = columns.value.filter((c) => !saved.columns.includes(c))
        const widthsMeanwhile = widths.value
        columns.value = saved.columns
        widths.value = saved.widths
        lastSaved = JSON.stringify(snapshot())
        columns.value = [...saved.columns, ...openedMeanwhile]
        widths.value = { ...saved.widths, ...widthsMeanwhile }
      }
    } catch {
      // Without the saved layout the workspace just starts empty.
    } finally {
      restoring = false
      closedMeanwhile.clear()
      restored.value = true
      scheduleSave() // writes only if it differs from what was read
    }
  }

  function snapshot(): SavedLayout {
    const kept: Record<string, number> = {}
    for (const id of columns.value) kept[id] = widthOf(id)
    return { columns: [...columns.value], widths: kept }
  }

  let timer: ReturnType<typeof setTimeout> | null = null
  let lastSaved: string | null = null

  function scheduleSave(): void {
    if (!restored.value || !canSave) return
    if (timer) clearTimeout(timer)
    timer = setTimeout(() => {
      timer = null
      const value = snapshot()
      const serialized = JSON.stringify(value)
      if (serialized === lastSaved) return
      lastSaved = serialized
      api.putAppState('layout', value).catch(() => {
        lastSaved = null // try again on the next change
      })
    }, SAVE_DELAY)
  }

  watch([columns, widths], scheduleSave, { deep: true })

  return { columns, widths, restored, finishedAfterDays, widthOf, isOpen, open, close, setWidth, restore }
})
