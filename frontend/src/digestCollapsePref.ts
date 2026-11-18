const KEY = 'maestro:digest-collapsed'

/** Whether the Resumo section of the details panel starts folded (default: folded). */
export function readDigestCollapsed(): boolean {
  try {
    return localStorage.getItem(KEY) !== 'false'
  } catch {
    return true
  }
}

export function writeDigestCollapsed(collapsed: boolean): void {
  try {
    localStorage.setItem(KEY, String(collapsed))
  } catch {
    // Without storage the choice lasts only for this page.
  }
}
