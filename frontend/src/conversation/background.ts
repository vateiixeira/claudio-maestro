import type { SubagentStatus, ToolItem } from '../types/conversation'

/** `unknown`: asked to run in the background, but no live status (history, or the CLI sent none). */
export type BackgroundState = SubagentStatus | 'unknown'

/** State of a Bash call run in the background; null for any other call. */
export function backgroundState(item: ToolItem): BackgroundState | null {
  if (item.name !== 'Bash') return null
  if (item.background) return item.background.status
  return item.input?.run_in_background === true ? 'unknown' : null
}

export const BACKGROUND_LABEL: Record<BackgroundState, string> = {
  running: 'Em background',
  completed: 'Concluído',
  failed: 'Falhou',
  stopped: 'Parado',
  unknown: 'Em background',
}
