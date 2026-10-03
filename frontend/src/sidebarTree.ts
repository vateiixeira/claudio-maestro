import { needsYou } from './conversation/needsYou'
import { isActive, sessionsOf, sortGroups } from './groupList'
import type { Project, Session, SessionGroup } from './types/api'

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

/**
 * Projects of the sidebar split in two: "Em andamento" (some conversation not finished) and the rest.
 * Both keep the order of `projects`, so a project moves between them without reshuffling the others.
 */
export function splitProjects(projects: Project[], sessions: Session[]): { active: Project[]; others: Project[] } {
  const withOpen = new Set<number>()
  for (const s of sessions) if (s.display_state !== 'finished') withOpen.add(s.project_id)
  const active: Project[] = []
  const others: Project[] = []
  for (const p of projects) (withOpen.has(p.id) ? active : others).push(p)
  return { active, others }
}
