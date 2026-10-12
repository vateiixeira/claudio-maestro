import { ref } from 'vue'

const KEY = 'maestro:theme'

export interface ThemeInfo {
  id: string
  label: string
}

/** The first one is the default (no `data-theme` on `<html>`); the others have a block in themes.css. Keep the ids in sync with the boot script in index.html. */
export const THEMES = [
  { id: 'maestro', label: 'Maestro' },
  { id: 'dracula', label: 'Dracula' },
  { id: 'monokai-pro', label: 'Monokai Pro' },
  { id: 'monokai-machine', label: 'Monokai Machine' },
  { id: 'monokai-octagon', label: 'Monokai Octagon' },
  { id: 'monokai-ristretto', label: 'Monokai Ristretto' },
  { id: 'monokai-spectrum', label: 'Monokai Spectrum' },
  { id: 'monokai-classic', label: 'Monokai Classic' },
] as const satisfies readonly ThemeInfo[]

export type ThemeId = (typeof THEMES)[number]['id']
export const THEME_DEFAULT: ThemeId = 'maestro'

function isThemeId(value: unknown): value is ThemeId {
  return THEMES.some((t) => t.id === value)
}

/** Theme saved in this browser, or the default when there is none, it is not a known theme, or storage fails. */
export function readTheme(): ThemeId {
  try {
    const raw = localStorage.getItem(KEY)
    return isThemeId(raw) ? raw : THEME_DEFAULT
  } catch {
    return THEME_DEFAULT
  }
}

export function applyTheme(id: ThemeId): void {
  const root = document.documentElement
  if (id === THEME_DEFAULT) root.removeAttribute('data-theme')
  else root.setAttribute('data-theme', id)
}

/** Current theme, shared with the Preferences screen. */
export const theme = ref<ThemeId>(readTheme())

/** Applies the theme right away and remembers it in this browser. Unknown ids are ignored. */
export function setTheme(id: string): void {
  if (!isThemeId(id)) return
  theme.value = id
  applyTheme(id)
  try {
    localStorage.setItem(KEY, id)
  } catch {
    // Without storage the choice lasts only for this page.
  }
}
