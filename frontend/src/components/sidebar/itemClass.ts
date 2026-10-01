import { needsYou, type NeedsYouFields } from '../../conversation/needsYou'

/** Classes of a sidebar entry; `active` marks the page being shown. */
export function sidebarItemClass(active: boolean): string[] {
  return [
    'flex min-h-10 items-center gap-2.5 rounded-lg px-3 no-underline hover:bg-card',
    active ? 'bg-card text-fg' : 'text-fg-muted hover:text-fg',
  ]
}

/** A waiting session is quiet (outline triangle, no orange) when `needsYou` is false. */
export function isQuietSession(s: NeedsYouFields): boolean {
  return !needsYou(s)
}
