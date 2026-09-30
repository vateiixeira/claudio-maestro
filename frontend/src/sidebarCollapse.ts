import { ref } from 'vue'

const KEY = 'vibing:sidebar-collapsed'

type Kind = 'project' | 'group'
type State = Record<Kind, number[]>

function ids(value: unknown): number[] {
  return Array.isArray(value) ? value.filter((v): v is number => Number.isInteger(v)) : []
}

function read(): State {
  try {
    const raw = localStorage.getItem(KEY)
    const value = raw ? (JSON.parse(raw) as Partial<State>) : {}
    return { project: ids(value?.project), group: ids(value?.group) }
  } catch {
    return { project: [], group: [] }
  }
}

/** Projects and groups the user collapsed in the sidebar. Everything else is open. */
export const collapsed = ref<State>(read())

export function isCollapsed(kind: Kind, id: number): boolean {
  return collapsed.value[kind].includes(id)
}

export function setCollapsed(kind: Kind, id: number, value: boolean): void {
  const rest = collapsed.value[kind].filter((v) => v !== id)
  collapsed.value = { ...collapsed.value, [kind]: value ? [...rest, id] : rest }
  try {
    localStorage.setItem(KEY, JSON.stringify(collapsed.value))
  } catch {
    // Without storage the choice lasts while the page is open.
  }
}
