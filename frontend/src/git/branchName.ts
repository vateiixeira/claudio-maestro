/** The one rule checked while typing; git checks the rest when the branch is created. */
export function branchNameProblem(name: string): string | null {
  const text = name.trim()
  if (!text.includes(' ')) return null
  return `Nome de branch não pode ter espaço. Por exemplo: ${text.replace(/ +/g, '-')}.`
}
