import { isDiscarded } from './conversation/marks'
import type { Project, Session, SessionGroup } from './types/api'

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

/** Groups seen from a project: the ones created in it (even empty) and the ones holding one of its open conversations. */
export function visibleGroups(groups: SessionGroup[], sessions: Session[], projectId: number): SessionGroup[] {
  const holding = new Set<number>()
  for (const s of sessions) if (s.project_id === projectId && s.group_id != null && !isDiscarded(s)) holding.add(s.group_id)
  return groups.filter((g) => g.project_id === projectId || holding.has(g.id))
}

/** Every group, for a selector: those visible in the project first, then the rest; each block by latest activity. */
export function selectorGroups(groups: SessionGroup[], sessions: Session[], projectId: number): SessionGroup[] {
  const visible = visibleGroups(groups, sessions, projectId)
  const ids = new Set(visible.map((g) => g.id))
  return [...sortGroups(visible, sessions), ...sortGroups(groups.filter((g) => !ids.has(g.id)), sessions)]
}

/** Selector text: the name, plus the project it was created in when that is not the project at hand. */
export function groupOptionLabel(group: SessionGroup, projectId: number, projects: Pick<Project, 'id' | 'name'>[]): string {
  if (group.project_id === projectId) return group.name
  const origin = projects.find((p) => p.id === group.project_id)
  return origin ? `${group.name} · ${origin.name}` : group.name
}

/** What removing a group does to its conversations, for the confirmation. They are released, never deleted. */
export function removeGroupText(members: Session[]): string {
  const n = members.length
  if (n === 0) return 'O agrupador está vazio.'
  if (n === 1) return 'A conversa volta a ficar solta; nenhuma é apagada.'
  const projects = new Set(members.map((s) => s.project_id)).size
  const from = projects > 1 ? `, de ${projects} projetos,` : ''
  return `As ${n} conversas${from} voltam a ficar soltas; nenhuma é apagada.`
}
