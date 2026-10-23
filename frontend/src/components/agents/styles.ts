// Class strings shared by the agent screens, in the look of the rest of the app.
const focus = 'focus-visible:outline-2 focus-visible:outline-primary'

export const BTN = `h-9 rounded-lg border border-line-strong bg-transparent px-3.5 text-sm font-medium text-fg hover:bg-card ${focus} disabled:cursor-default disabled:opacity-50`
export const BTN_PRIMARY = `h-9 rounded-lg border-0 bg-primary px-3.5 text-sm font-semibold text-primary-fg hover:bg-primary-soft ${focus} disabled:cursor-default disabled:opacity-50`
export const BTN_SMALL = `h-7 rounded-md border border-line-strong bg-transparent px-2.5 text-xs font-medium text-fg-muted hover:bg-card hover:text-fg ${focus} disabled:cursor-default disabled:opacity-50`
export const FIELD = `h-9 rounded-lg border border-line-strong bg-surface px-2.5 text-sm text-fg placeholder:text-fg-subtle ${focus}`
export const AREA = `w-full resize-y rounded-lg border border-line-strong bg-surface p-2.5 text-sm leading-relaxed text-fg placeholder:text-fg-subtle ${focus}`
export const ERROR = 'm-0 text-sm text-diff-del-fg'
