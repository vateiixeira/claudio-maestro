import type { Turn, TurnEntry } from './turns'

/** How close to the end of the conversation (px) the user still counts as "at the end". */
export const FOLLOW_DISTANCE = 80

/** The key of one row of the rail; a work block keeps its key while it grows. */
export function entryKey(entry: TurnEntry): string {
  return entry.kind === 'group' ? `group-${entry.id}` : entry.item.id
}

export const promptKey = (promptId: string) => `prompt:${promptId}`

/** Every key the thread shows: user messages, rail rows and pending requests. */
export function turnKeys(turns: Turn[], prompts: ReadonlyArray<{ prompt_id: string }>): Set<string> {
  const keys = new Set<string>()
  for (const turn of turns) {
    if (turn.user) keys.add(turn.user.id)
    for (const entry of turn.entries) keys.add(entryKey(entry))
  }
  for (const prompt of prompts) keys.add(promptKey(prompt.prompt_id))
  return keys
}

type Scrollable = Pick<HTMLElement, 'scrollHeight' | 'scrollTop' | 'clientHeight'>

export const distanceToEnd = (el: Scrollable) => el.scrollHeight - el.scrollTop - el.clientHeight
export const isNearEnd = (el: Scrollable, distance = FOLLOW_DISTANCE) => distanceToEnd(el) < distance
