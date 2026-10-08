import { isDiscarded } from './conversation/marks'
import type { Session, SessionGroup } from './types/api'

/** Whether the session still counts as work in progress (not finished, not discarded). */
export function isActive(session: Session): boolean {
  return session.display_state !== 'finished' && !isDiscarded(session)
}

/** Sessions of a group, newest activity first. */
export function sessionsOf(groupId: number, list: Session[]): Session[] {
  return list
    .filter((s) => s.group_id === groupId)
    .sort((a, b) => b.last_activity_at - a.last_activity_at || b.created_at - a.created_at)
}

/** Latest activity of the group's sessions; its creation when it has none. */
export function groupActivity(group: SessionGroup, list: Session[]): number {
  return sessionsOf(group.id, list)[0]?.last_activity_at ?? group.created_at
}

/** Groups by latest activity, newest first. */
export function sortGroups(groups: SessionGroup[], list: Session[]): SessionGroup[] {
  return [...groups].sort((a, b) => groupActivity(b, list) - groupActivity(a, list) || b.id - a.id)
}
