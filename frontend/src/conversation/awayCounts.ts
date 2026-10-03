import type { ConversationItem } from '../types/conversation'
import { TASK_TOOLS } from './tasks'
import { EDIT_TOOLS } from './turns'

/** How long the user must have been away for the "while you were away" card. */
export const AWAY_AFTER_SECONDS = 15 * 60

/** Tools that ask the user something: the card does not count them as work. */
const ASK_TOOLS = new Set(['AskUserQuestion', 'ExitPlanMode'])

export interface AwayCounts {
  turns: number
  actions: number
  files: number
}

/**
 * The card shows when the conversation was last seen more than 15 minutes ago and something
 * happened after that. A conversation never seen has no moment to compare with.
 */
export function shouldShowAway(input: { lastSeenAt: number | null | undefined; lastActivityAt: number; now: number }): boolean {
  const { lastSeenAt, lastActivityAt, now } = input
  if (!lastSeenAt) return false
  return now - lastSeenAt > AWAY_AFTER_SECONDS && lastActivityAt > lastSeenAt
}

/**
 * What the items created after `since` (Unix seconds) add up to. A turn is a user message and
 * what follows it, so the turn that was already running when the user left counts once if it kept
 * working. Actions are tool calls, subagents' included; files are the distinct paths edited.
 * Items without a time (old transcripts) are left out.
 */
export function awayCounts(items: ConversationItem[], since: number): AwayCounts {
  let turns = 0
  let actions = 0
  let segmentCounted = false
  const files = new Set<string>()
  for (const item of items) {
    if (item.type === 'user') segmentCounted = false
    if (item.at == null || item.at <= since) continue
    if (!segmentCounted) {
      segmentCounted = true
      turns++
    }
    if (item.type !== 'tool' || TASK_TOOLS.has(item.name) || ASK_TOOLS.has(item.name)) continue
    actions++
    const path = item.input.file_path
    if (EDIT_TOOLS.has(item.name) && typeof path === 'string' && path) files.add(path)
  }
  return { turns, actions, files: files.size }
}
