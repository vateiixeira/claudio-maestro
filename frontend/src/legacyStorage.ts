/** Keys no version of the app reads anymore. */
const DROPPED_KEYS = [
  // Recentes used to be the conversations opened here; now it lists by last interaction.
  'vibing:recent-conversations',
]

// The app was called Vini7 Vibing before going public: its keys used the `vibing:` prefix.
const OLD_PREFIX = 'vibing:'
const NEW_PREFIX = 'maestro:'

function storageKeys(): string[] {
  const keys: string[] = []
  for (let i = 0; i < localStorage.length; i++) {
    const key = localStorage.key(i)
    if (key !== null) keys.push(key)
  }
  return keys
}

/**
 * Drop keys of removed features and move `vibing:*` to `maestro:*` (an existing
 * new key wins). Safe to run on every start.
 */
export function migrateLegacyStorage(): void {
  try {
    for (const key of DROPPED_KEYS) localStorage.removeItem(key)
    for (const key of storageKeys()) {
      if (!key.startsWith(OLD_PREFIX)) continue
      const value = localStorage.getItem(key)
      const renamed = NEW_PREFIX + key.slice(OLD_PREFIX.length)
      if (value !== null && localStorage.getItem(renamed) === null) localStorage.setItem(renamed, value)
      localStorage.removeItem(key)
    }
  } catch {
    // Without storage there is nothing to migrate.
  }
}
