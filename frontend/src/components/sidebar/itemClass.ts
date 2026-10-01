/** Classes of a sidebar entry; `active` marks the page being shown. */
export function sidebarItemClass(active: boolean): string[] {
  return [
    'flex min-h-10 items-center gap-2.5 rounded-lg px-3 no-underline hover:bg-card',
    active ? 'bg-card text-fg' : 'text-fg-muted hover:text-fg',
  ]
}

/** A waiting session is quiet (grey triangle) only when it has nothing new, no prompt waiting and no error. */
export function isQuietSession(s: { unread: boolean; pending_kind?: string | null; state: string }): boolean {
  return !s.unread && !s.pending_kind && s.state !== 'error'
}
