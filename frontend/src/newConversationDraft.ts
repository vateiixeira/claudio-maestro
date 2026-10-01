import { ALL_EFFORTS, SELECTABLE_MODES } from './sessionOptions'
import type { Effort, PermissionMode } from './types/api'

const KEY = 'maestro:new-conversation'
const LAST_PROJECT_KEY = 'maestro:new-conversation-last-project'

export interface ConversationDraft {
  projectId: number | null
  groupId: number | null
  title: string
  prompt: string
  model: string | null
  effort: Effort | null
  permissionMode: PermissionMode | null
}

export function emptyDraft(): ConversationDraft {
  return { projectId: null, groupId: null, title: '', prompt: '', model: null, effort: null, permissionMode: null }
}

/** The saved draft, or an empty one when there is none, it is invalid or storage fails. */
export function loadDraft(): ConversationDraft {
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return emptyDraft()
    const value = JSON.parse(raw) as Partial<ConversationDraft>
    return {
      projectId: typeof value.projectId === 'number' ? value.projectId : null,
      groupId: typeof value.groupId === 'number' ? value.groupId : null,
      title: typeof value.title === 'string' ? value.title : '',
      prompt: typeof value.prompt === 'string' ? value.prompt : '',
      model: typeof value.model === 'string' ? value.model : null,
      effort: ALL_EFFORTS.includes(value.effort as Effort) ? (value.effort as Effort) : null,
      permissionMode: SELECTABLE_MODES.includes(value.permissionMode as PermissionMode) ? (value.permissionMode as PermissionMode) : null,
    }
  } catch {
    return emptyDraft()
  }
}

export function saveDraft(draft: ConversationDraft): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(draft))
  } catch {
    // Without storage the draft lives only while the page is open.
  }
}

export function clearDraft(): void {
  try {
    localStorage.removeItem(KEY)
  } catch {
    // Nothing to clear.
  }
}

/** The project of the last conversation started from the modal, kept apart from the draft. */
export function loadLastProject(): number | null {
  try {
    const value = Number(localStorage.getItem(LAST_PROJECT_KEY))
    return Number.isInteger(value) && value > 0 ? value : null
  } catch {
    return null
  }
}

export function saveLastProject(projectId: number): void {
  try {
    localStorage.setItem(LAST_PROJECT_KEY, String(projectId))
  } catch {
    // Without storage the default project is the first available one.
  }
}
