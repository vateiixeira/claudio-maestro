import { needsYou, type NeedsYouFields } from '../../conversation/needsYou'

/** Classes of a sidebar entry; `active` marks the page being shown. */
export function sidebarItemClass(active: boolean): string[] {
  return [
    'flex min-h-[34px] items-center gap-2.5 rounded-lg px-2.5 no-underline hover:bg-card',
    active ? 'bg-card text-fg' : 'text-fg-muted hover:text-fg',
  ]
}

/** Classes of a conversation nested under its project: smaller, dimmer unless it needs you or is running. */
export function sidebarNestedItemClass(active: boolean, prominent: boolean): string[] {
  return [
    'flex min-h-7 items-center gap-2 rounded-md px-2 no-underline hover:bg-card',
    active ? 'bg-card text-fg' : prominent ? 'text-fg-muted hover:text-fg' : 'text-fg-subtle hover:text-fg',
  ]
}

/** A waiting session is quiet (outline triangle, no orange) when `needsYou` is false. */
export function isQuietSession(s: NeedsYouFields): boolean {
  return !needsYou(s)
}
