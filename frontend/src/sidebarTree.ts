import { needsYou } from './conversation/needsYou'
import { isActive, sessionsOf, sortGroups } from './groupList'
import type { Project, Session, SessionGroup } from './types/api'

export interface ActiveGroup {
  group: SessionGroup
  sessions: Session[]
  waiting: number
}

/** An agent's session (a run or its main conversation) is listed in the "Agentes" section, not under projects and groups. */
const isOrdinary = (s: Session) => s.agent_id == null

/** Groups of one project for the sidebar: only those with active sessions, listing only those sessions. A group with none is left out. */
export function projectTree(groups: SessionGroup[], sessions: Session[]): ActiveGroup[] {
  const active: ActiveGroup[] = []
  for (const group of sortGroups(groups, sessions)) {
    const open = sessionsOf(group.id, sessions).filter((s) => isActive(s) && isOrdinary(s))
    if (open.length > 0) active.push({ group, sessions: open, waiting: open.filter((s) => s.display_state === 'waiting' && needsYou(s)).length })
  }
  return active
}

/**
 * Projects of the sidebar split in two: "Em andamento" (some conversation not finished) and the rest.
 * Both keep the order of `projects`, so a project moves between them without reshuffling the others.
 */
export function splitProjects(projects: Project[], sessions: Session[]): { active: Project[]; others: Project[] } {
  const withOpen = new Set<number>()
  for (const s of sessions) if (isActive(s) && isOrdinary(s)) withOpen.add(s.project_id)
  const active: Project[] = []
  const others: Project[] = []
  for (const p of projects) (withOpen.has(p.id) ? active : others).push(p)
  return { active, others }
}
