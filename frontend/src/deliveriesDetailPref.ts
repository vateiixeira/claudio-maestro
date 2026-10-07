const KEY = 'maestro:deliveries-detail'

/** Whether "Entregas" shows every bullet of every record (default: only the first). */
export function readDeliveriesDetail(): boolean {
  try {
    return localStorage.getItem(KEY) === 'true'
  } catch {
    return false
  }
}

export function writeDeliveriesDetail(detailed: boolean): void {
  try {
    localStorage.setItem(KEY, String(detailed))
  } catch {
    // Without storage the choice lasts only for this page.
  }
}
