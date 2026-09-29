/** Editor command as the backend keeps it: a list of arguments, without a shell. */

/** Splits a line into arguments; double or single quotes group words with spaces. */
export function parseEditorCommand(text: string): string[] {
  const parts: string[] = []
  let current = ''
  let started = false
  let quote: '"' | "'" | null = null
  for (const char of text) {
    if (quote) {
      if (char === quote) quote = null
      else current += char
    } else if (char === '"' || char === "'") {
      quote = char
      started = true
    } else if (/\s/.test(char)) {
      if (started) parts.push(current)
      current = ''
      started = false
    } else {
      current += char
      started = true
    }
  }
  if (quote) throw new Error('Aspas sem fechar.')
  if (started) parts.push(current)
  return parts
}

/** Why a parsed command cannot be saved, or null. The backend refuses empty arguments (`code ""`). */
export function editorCommandProblem(command: string[]): string | null {
  return command.some((part) => part === '')
    ? 'O comando do editor tem um argumento vazio (aspas sem nada dentro). Remova as aspas vazias.'
    : null
}

/** The inverse of `parseEditorCommand`: quotes only the parts that need it. */
export function formatEditorCommand(command: string[]): string {
  return command
    .map((part) => {
      if (part !== '' && !/[\s"']/.test(part)) return part
      return part.includes('"') ? `'${part}'` : `"${part}"`
    })
    .join(' ')
}
