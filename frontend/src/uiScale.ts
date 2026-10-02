import { ref } from 'vue'

const KEY = 'maestro:ui-scale'

/** Root font size, in percent. Every font size in the app is in rem, so this scales all text together. */
export const UI_SCALES = [90, 100, 112.5, 125, 137.5, 150] as const
export const UI_SCALE_DEFAULT = 100

function isUiScale(value: number): boolean {
  return (UI_SCALES as readonly number[]).includes(value)
}

/** Scale saved in this browser, or the default when there is none, it is not one of the options, or storage fails. */
export function readUiScale(): number {
  try {
    const raw = localStorage.getItem(KEY)
    const value = raw === null ? Number.NaN : Number(raw)
    return isUiScale(value) ? value : UI_SCALE_DEFAULT
  } catch {
    return UI_SCALE_DEFAULT
  }
}

export function applyUiScale(scale: number): void {
  document.documentElement.style.fontSize = `${scale}%`
}

/** Current scale, shared with the Preferences screen. */
export const uiScale = ref<number>(readUiScale())

/** Applies the scale right away and remembers it in this browser. Values outside the options are ignored. */
export function setUiScale(scale: number): void {
  if (!isUiScale(scale)) return
  uiScale.value = scale
  applyUiScale(scale)
  try {
    localStorage.setItem(KEY, String(scale))
  } catch {
    // Without storage the choice lasts only for this page.
  }
}
