import { sidebarWidth } from './sidebarWidthPref'

const KEY = 'maestro:details-width'
export const DETAILS_DEFAULT_WIDTH = 360
export const DETAILS_MIN_WIDTH = 300
export const DETAILS_KEY_STEP = 16

/**
 * Widest the panel may be: 70% of the window, leaving at least 400px for the
 * conversation beside the sidebar. As a drawer (it overlays the conversation) only
 * the 70% applies.
 */
export function detailsMaxWidth(viewport: number, drawer = false): number {
  const share = Math.floor(viewport * 0.7)
  return Math.max(DETAILS_MIN_WIDTH, drawer ? share : Math.min(share, viewport - 400 - sidebarWidth.value))
}

export function clampDetailsWidth(width: number, viewport: number, drawer = false): number {
  return Math.round(Math.min(Math.max(width, DETAILS_MIN_WIDTH), detailsMaxWidth(viewport, drawer)))
}

/** Width chosen by the user (default 360). Limits are applied where it is shown. */
export function readDetailsWidth(): number {
  try {
    const value = Number.parseInt(localStorage.getItem(KEY) ?? '', 10)
    return Number.isFinite(value) && value > 0 ? value : DETAILS_DEFAULT_WIDTH
  } catch {
    return DETAILS_DEFAULT_WIDTH
  }
}

export function writeDetailsWidth(width: number): void {
  try {
    localStorage.setItem(KEY, String(Math.round(width)))
  } catch {
    // Without storage the width lasts only for this page.
  }
}
