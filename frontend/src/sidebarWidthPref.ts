import { ref } from 'vue'

const KEY = 'maestro:sidebar-width'
export const SIDEBAR_DEFAULT_WIDTH = 288
export const SIDEBAR_MIN_WIDTH = 240
export const SIDEBAR_MAX_WIDTH = 480
export const SIDEBAR_KEY_STEP = 16

export function clampSidebarWidth(width: number): number {
  return Math.round(Math.min(SIDEBAR_MAX_WIDTH, Math.max(SIDEBAR_MIN_WIDTH, width)))
}

/** Width chosen by the user for the left sidebar (default 288), within the limits. */
export function readSidebarWidth(): number {
  try {
    const value = Number.parseInt(localStorage.getItem(KEY) ?? '', 10)
    return Number.isFinite(value) ? clampSidebarWidth(value) : SIDEBAR_DEFAULT_WIDTH
  } catch {
    return SIDEBAR_DEFAULT_WIDTH
  }
}

export function writeSidebarWidth(width: number): void {
  try {
    localStorage.setItem(KEY, String(Math.round(width)))
  } catch {
    // Without storage the width lasts only for this page.
  }
}

/** Current sidebar width, shared so the Details panel can leave room for it. */
export const sidebarWidth = ref(readSidebarWidth())
