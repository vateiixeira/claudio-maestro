const KEY = 'maestro:details-tab'

export type DetailsTab = 'details' | 'terminal' | 'git'

/** The tab the details panel starts on (default: Detalhes). */
export function readDetailsTab(): DetailsTab {
  try {
    const stored = localStorage.getItem(KEY)
    return stored === 'terminal' || stored === 'git' ? stored : 'details'
  } catch {
    return 'details'
  }
}

export function writeDetailsTab(tab: DetailsTab): void {
  try {
    localStorage.setItem(KEY, tab)
  } catch {
    // Without storage the choice lasts only for this page.
  }
}
