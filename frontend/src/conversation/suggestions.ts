// Pure helpers of the `/` and `@` suggestion menus. Behavior follows the VS Code
// extension: the trigger is the token under the cursor, choosing replaces it.
import type { CommandInfo } from '../types/api'

export type TriggerKind = 'command' | 'mention'

export interface Trigger {
  kind: TriggerKind
  /** Index of the `@` or `/`. */
  start: number
  /** End of the token (exclusive). */
  end: number
  query: string
}

const PATTERNS: [TriggerKind, RegExp][] = [
  ['mention', /(^|\s)@[^\s]*/g],
  // The CLI only runs a command when the prompt starts with `/`, so this one is anchored to the
  // first non-whitespace character of the whole text.
  ['command', /^(\s*)\/[^\s/]*/g],
]

export function findTrigger(text: string, cursor: number): Trigger | null {
  for (const [kind, pattern] of PATTERNS) {
    for (const match of text.matchAll(pattern)) {
      const start = (match.index ?? 0) + match[1].length
      const end = (match.index ?? 0) + match[0].length
      if (cursor > start && cursor <= end) return { kind, start, end, query: text.slice(start + 1, end) }
    }
  }
  return null
}

export function applySuggestion(
  text: string,
  trigger: Trigger,
  insert: string,
  addSpace: boolean,
): { text: string; cursor: number } {
  const before = text.slice(0, trigger.start) + insert
  const after = text.slice(trigger.end)
  if (!addSpace) return { text: before + after, cursor: before.length }
  if (/^\s/.test(after)) return { text: before + after, cursor: before.length + 1 }
  return { text: before + ' ' + after, cursor: before.length + 1 }
}

export function quotePath(path: string): string {
  return /[\s"#]/.test(path) ? `"${path}"` : path
}

export function mentionText(path: string): string {
  return '@' + quotePath(path)
}

/**
 * Where each mention occurs in the text, as sorted, non-overlapping [start, end) pairs.
 * An occurrence counts only at the start or after whitespace, and before whitespace or the end.
 */
export function mentionRanges(text: string, mentions: Iterable<string>): [number, number][] {
  const found: [number, number][] = []
  for (const mention of mentions) {
    if (!mention) continue
    let from = 0
    for (;;) {
      const at = text.indexOf(mention, from)
      if (at < 0) break
      const end = at + mention.length
      if ((at === 0 || /\s/.test(text[at - 1])) && (end === text.length || /\s/.test(text[end]))) found.push([at, end])
      from = at + 1
    }
  }
  found.sort((a, b) => a[0] - b[0] || b[1] - a[1])
  const result: [number, number][] = []
  for (const range of found) {
    if (!result.length || range[0] >= result[result.length - 1][1]) result.push(range)
  }
  return result
}

function subsequenceAt(name: string, term: string): number {
  let from = 0
  let first = -1
  for (const char of term) {
    const at = name.indexOf(char, from)
    if (at < 0) return -1
    if (first < 0) first = at
    from = at + 1
  }
  return first
}

export function rankCommands(commands: CommandInfo[], term: string): CommandInfo[] {
  const byName = (a: CommandInfo, b: CommandInfo) => a.name.localeCompare(b.name)
  const q = term.toLowerCase()
  if (!q) return [...commands].sort(byName)
  const ranked: { command: CommandInfo; group: number; position: number }[] = []
  for (const command of commands) {
    const name = command.name.toLowerCase()
    let group = -1
    let position = 0
    if (name === q) group = 0
    else if (name.startsWith(q)) group = 1
    else if (name.includes(q)) [group, position] = [2, name.indexOf(q)]
    else if (subsequenceAt(name, q) >= 0) [group, position] = [2, subsequenceAt(name, q)]
    else if (command.description.toLowerCase().includes(q)) {
      ;[group, position] = [3, command.description.toLowerCase().indexOf(q)]
    }
    if (group >= 0) ranked.push({ command, group, position })
  }
  ranked.sort(
    (a, b) =>
      a.group - b.group ||
      a.position - b.position ||
      a.command.name.length - b.command.name.length ||
      byName(a.command, b.command),
  )
  return ranked.map((r) => r.command)
}
