import type { InjectionKey, Ref } from 'vue'

export interface AgentsNavigation {
  enabled: Ref<boolean>
  open: Ref<boolean>
  toggle: (trigger: HTMLElement) => void
}
export const AGENTS_NAVIGATION_KEY: InjectionKey<AgentsNavigation> = Symbol('agents-navigation')
