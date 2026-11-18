// Short name of a model for the composer bar: drops a trailing parenthetical,
// e.g. "Default (recommended)" becomes "Default". The full name stays in the
// accessible name and the title.
export function shortModelLabel(name: string): string {
  const trimmed = name.trim()
  const short = trimmed.replace(/\s*\([^()]*\)$/, '').trim()
  return short || trimmed
}
