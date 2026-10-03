import type { InjectionKey } from 'vue'

/**
 * A conversation provides this so it knows when a `Collapse` starts to open. The content of a row
 * has no height until the transition ends; whoever scrolls to it right after opening it waits for that.
 */
export const COLLAPSE_OPENING_KEY: InjectionKey<() => void> = Symbol('collapse-opening')
