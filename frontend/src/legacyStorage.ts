/** Keys no version of the app reads anymore. */
const LEGACY_KEYS = [
  // Recentes used to be the conversations opened here; now it lists by last interaction.
  'vibing:recent-conversations',
]

/** Drop the keys left behind by removed features. Safe to run on every start. */
export function removeLegacyStorage(): void {
  try {
    for (const key of LEGACY_KEYS) localStorage.removeItem(key)
  } catch {
    // Without storage there is nothing to clean.
  }
}
