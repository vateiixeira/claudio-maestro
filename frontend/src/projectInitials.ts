/** Two-letter tag of a project: first letters of its first two words, or the first two letters. */
export function projectInitials(name: string): string {
  const plain = name.normalize('NFD').replace(/[̀-ͯ]/g, '')
  const words = plain
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .split(/[\s\-_.]+/)
    .filter(Boolean)
  if (words.length === 0) return '?'
  const letters = words.length >= 2 ? words[0]!.charAt(0) + words[1]!.charAt(0) : words[0]!.slice(0, 2)
  return letters.toUpperCase()
}
