const FALLBACK = '#6b7280'

/** Color suggested for a new label (a user choice, so it may be a literal). */
export const DEFAULT_LABEL_COLOR = '#6366f1'

/** `#abc` → `#aabbcc`; lower case. `null` when it is not a hex color. */
function normalize(hex: string): string | null {
  const value = hex.trim().toLowerCase()
  if (/^#[0-9a-f]{6}$/.test(value)) return value
  if (/^#[0-9a-f]{3}$/.test(value)) return `#${[...value.slice(1)].map((c) => c + c).join('')}`
  return null
}

function luminance(hex: string): number {
  const channel = (start: number) => {
    const c = parseInt(hex.slice(start, start + 2), 16) / 255
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
  }
  return 0.2126 * channel(1) + 0.7152 * channel(3) + 0.0722 * channel(5)
}

/** Black or white, whichever reads better on `hex` (WCAG contrast ratio). */
export function contrastText(hex: string): '#000000' | '#ffffff' {
  const color = normalize(hex) ?? FALLBACK
  const l = luminance(color)
  const withWhite = 1.05 / (l + 0.05)
  const withBlack = (l + 0.05) / 0.05
  return withWhite >= withBlack ? '#ffffff' : '#000000'
}

/** Solid fill in the label's color: the contrast holds in every theme. */
export function labelStyle(hex: string): { backgroundColor: string; color: string } {
  const color = normalize(hex) ?? FALLBACK
  return { backgroundColor: color, color: contrastText(color) }
}
