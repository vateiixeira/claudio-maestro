import { ref } from 'vue'

const KEY = 'maestro:theme'

export interface ThemeInfo {
  id: string
  label: string
  /** [background, text, green, orange] of the theme, for the sample in Preferences. */
  swatch: readonly [string, string, string, string]
}

/** The first one is the default (no `data-theme` on `<html>`); the others have a block in themes.css. Keep the ids in sync with the boot script in index.html. */
export const THEMES = [
  { id: 'maestro', label: 'Maestro', swatch: ['#0b0b0c', '#f4f4f5', '#4ade80', '#fb923c'] },
  { id: 'dracula', label: 'Dracula', swatch: ['#21222c', '#f8f8f2', '#50fa7b', '#ffb86c'] },
  { id: 'monokai-pro', label: 'Monokai Pro', swatch: ['#221f22', '#fcfcfa', '#a9dc76', '#fc9867'] },
  { id: 'monokai-machine', label: 'Monokai Machine', swatch: ['#1d2528', '#f2fffc', '#a2e57b', '#ffb270'] },
  { id: 'monokai-octagon', label: 'Monokai Octagon', swatch: ['#1e1f2b', '#eaf2f1', '#bad761', '#ff9b5e'] },
  { id: 'monokai-ristretto', label: 'Monokai Ristretto', swatch: ['#211c1c', '#fff1f3', '#adda78', '#f38d70'] },
  { id: 'monokai-spectrum', label: 'Monokai Spectrum', swatch: ['#191919', '#f7f1ff', '#7bd88f', '#fd9353'] },
  { id: 'monokai-classic', label: 'Monokai Classic', swatch: ['#1d1e19', '#fdfff1', '#a6e22e', '#fd971f'] },
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
