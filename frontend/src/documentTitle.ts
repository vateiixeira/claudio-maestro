/** Browser tab title with the number of conversations waiting for the user. */
export function documentTitle(waiting: number): string {
  return waiting > 0 ? `(${waiting}) Cláudio Maestro` : 'Cláudio Maestro'
}
