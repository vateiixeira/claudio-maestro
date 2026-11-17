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

/** Share of the label color in the badge background, over the surface. */
export const LABEL_TINT = 24

/** The fixed colors offered for a new label, in the order they show. */
export const LABEL_PALETTE: readonly string[] = ['#ff6188', '#fc9867', '#ffd866', '#a9dc76', '#78dce8', '#ab9df2', '#9e9d9d']

/** `percent` of `color` over `base`, both `#rrggbb` (sRGB, like CSS `color-mix`). */
export function mixHex(color: string, base: string, percent: number): string {
  const amount = percent / 100
  const channel = (hex: string, start: number) => parseInt(hex.slice(start, start + 2), 16)
  const mixed = [1, 3, 5].map((start) => {
    const value = Math.round(channel(color, start) * amount + channel(base, start) * (1 - amount))
    return value.toString(16).padStart(2, '0')
  })
  return `#${mixed.join('')}`
}

/** Tinted fill with the label's color; the dot carries the full color. The text stays in the theme's `fg`. */
export function labelStyle(hex: string): { backgroundColor: string; color: string; '--label-dot': string } {
  const color = normalize(hex) ?? FALLBACK
  return {
    backgroundColor: `color-mix(in srgb, ${color} ${LABEL_TINT}%, var(--color-elevated))`,
    color: 'var(--color-fg)',
    '--label-dot': color,
  }
}
