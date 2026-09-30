const KEY = 'vibing:project-split'

export const SPLIT_MIN = 30
export const SPLIT_MAX = 70
export const SPLIT_DEFAULT = 50

export function clampSplit(percent: number): number {
  return Math.min(SPLIT_MAX, Math.max(SPLIT_MIN, percent))
}

/** Width of the project pane, in percent, when a conversation is open beside it. */
export function readSplitPercent(): number {
  try {
    const raw = localStorage.getItem(KEY)
    if (raw === null || raw.trim() === '') return SPLIT_DEFAULT
    const value = Number(raw)
    return Number.isFinite(value) ? clampSplit(value) : SPLIT_DEFAULT
  } catch {
    return SPLIT_DEFAULT
  }
}

export function writeSplitPercent(percent: number): void {
  try {
    localStorage.setItem(KEY, String(percent))
  } catch {
    // Without storage the choice lasts only for this page.
  }
}
