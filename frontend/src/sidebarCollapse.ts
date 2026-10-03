import { ref } from 'vue'

const KEY = 'maestro:sidebar-collapsed'

type Kind = 'project' | 'group'
type State = Record<Kind, number[]> & { section: string[] }

function ids(value: unknown): number[] {
  return Array.isArray(value) ? value.filter((v): v is number => Number.isInteger(v)) : []
}

function names(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string') : []
}

function read(): State {
  try {
    const raw = localStorage.getItem(KEY)
    const value = raw ? (JSON.parse(raw) as Partial<State>) : {}
    return { project: ids(value?.project), group: ids(value?.group), section: names(value?.section) }
  } catch {
    return { project: [], group: [], section: [] }
  }
}

/** Projects, groups and sections the user collapsed in the sidebar. Everything else is open. */
export const collapsed = ref<State>(read())

function save(): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(collapsed.value))
  } catch {
    // Without storage the choice lasts while the page is open.
  }
}

export function isCollapsed(kind: Kind, id: number): boolean {
  return collapsed.value[kind].includes(id)
}

export function setCollapsed(kind: Kind, id: number, value: boolean): void {
  const rest = collapsed.value[kind].filter((v) => v !== id)
  collapsed.value = { ...collapsed.value, [kind]: value ? [...rest, id] : rest }
  save()
}

/** A named sidebar section (for now only "open", the "Abertas" list). */
export function isSectionCollapsed(name: string): boolean {
  return collapsed.value.section.includes(name)
}

export function setSectionCollapsed(name: string, value: boolean): void {
  const rest = collapsed.value.section.filter((v) => v !== name)
  collapsed.value = { ...collapsed.value, section: value ? [...rest, name] : rest }
  save()
}

/** Sections that start collapsed ("Depois") remember being opened, kept as "+name". */
export function isSectionOpened(name: string): boolean {
  return collapsed.value.section.includes(`+${name}`)
}

export function setSectionOpened(name: string, value: boolean): void {
  setSectionCollapsed(`+${name}`, value)
}
