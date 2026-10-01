import { needsYou } from './conversation/needsYou'
import { isActive, sessionsOf, sortGroups } from './groupList'
import type { Session, SessionGroup } from './types/api'

export interface ActiveGroup {
  group: SessionGroup
  sessions: Session[]
  waiting: number
}

/** Groups of one project for the sidebar: those with active sessions (only those listed) and the idle rest. */
export function projectTree(groups: SessionGroup[], sessions: Session[]): { active: ActiveGroup[]; idle: SessionGroup[] } {
  const active: ActiveGroup[] = []
  const idle: SessionGroup[] = []
  for (const group of sortGroups(groups, sessions)) {
    const open = sessionsOf(group.id, sessions).filter(isActive)
    if (open.length === 0) idle.push(group)
    else active.push({ group, sessions: open, waiting: open.filter((s) => s.display_state === 'waiting' && needsYou(s)).length })
  }
  return { active, idle }
}
