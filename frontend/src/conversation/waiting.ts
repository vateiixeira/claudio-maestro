import type { ConversationItem, PermissionPrompt } from '../types/conversation'

/** The actions that wait for the user: the tool of each pending request and the subagents it runs inside. */
export function waitingIdsOf(items: readonly ConversationItem[], prompts: readonly PermissionPrompt[]): Set<string> {
  const ids = new Set<string>()
  if (!prompts.length) return ids
  const byToolUse = new Map(items.flatMap((i) => (i.type === 'tool' ? [[i.tool_use_id, i] as const] : [])))
  for (const prompt of prompts) {
    for (let id: string | null | undefined = prompt.tool_use_id; id && !ids.has(id); ) {
      ids.add(id)
      id = byToolUse.get(id)?.parent_tool_use_id
    }
  }
  return ids
}
