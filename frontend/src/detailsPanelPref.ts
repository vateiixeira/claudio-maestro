const KEY = 'maestro:details-open'

/** Whether the details panel starts open on wide screens (default: open). */
export function readDetailsOpen(): boolean {
  try {
    return localStorage.getItem(KEY) !== 'false'
  } catch {
    return true
  }
}

export function writeDetailsOpen(open: boolean): void {
  try {
    localStorage.setItem(KEY, String(open))
  } catch {
    // Without storage the choice lasts only for this page.
  }
}
