const KEY = 'vibing:details-width'
export const DETAILS_DEFAULT_WIDTH = 360
export const DETAILS_MIN_WIDTH = 300
export const DETAILS_KEY_STEP = 16

/** Width of the app sidebar; matches its `w-64`. */
export const SIDEBAR_WIDTH = 256

/** Widest the panel may be: 70% of the window, leaving at least 400px for the conversation beside the sidebar. */
export function detailsMaxWidth(viewport: number): number {
  return Math.max(DETAILS_MIN_WIDTH, Math.min(Math.floor(viewport * 0.7), viewport - 400 - SIDEBAR_WIDTH))
}

export function clampDetailsWidth(width: number, viewport: number): number {
  return Math.round(Math.min(Math.max(width, DETAILS_MIN_WIDTH), detailsMaxWidth(viewport)))
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
