import { needsYou, type NeedsYouFields } from '../../conversation/needsYou'

/**
 * Classes of a sidebar entry; `active` marks the page being shown.
 * `twoLines` is for a conversation with labels: two columns (icon | title line, labels line) and a little vertical padding.
 */
export function sidebarItemClass(active: boolean, twoLines = false): string[] {
  return [
    twoLines
      ? 'grid min-h-[34px] grid-cols-[auto_minmax(0,1fr)] items-center gap-x-2.5 gap-y-0.5 rounded-lg px-2.5 py-1 no-underline hover:bg-card'
      : 'flex min-h-[34px] items-center gap-2.5 rounded-lg px-2.5 no-underline hover:bg-card',
    active ? 'bg-card text-fg' : 'text-fg-muted hover:text-fg',
  ]
}

/** Classes of a conversation nested under its project: smaller, dimmer unless it needs you or is running. */
export function sidebarNestedItemClass(active: boolean, prominent: boolean, twoLines = false): string[] {
  return [
    twoLines
      ? 'grid min-h-7 grid-cols-[auto_minmax(0,1fr)] items-center gap-x-2 gap-y-0.5 rounded-md px-2 py-1 no-underline hover:bg-card'
      : 'flex min-h-7 items-center gap-2 rounded-md px-2 no-underline hover:bg-card',
    active ? 'bg-card text-fg' : prominent ? 'text-fg-muted hover:text-fg' : 'text-fg-subtle hover:text-fg',
  ]
}

/** A waiting session is quiet (outline triangle, no orange) when `needsYou` is false. */
export function isQuietSession(s: NeedsYouFields): boolean {
  return !needsYou(s)
}
