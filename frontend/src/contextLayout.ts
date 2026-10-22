import type { ContextBreakdown, ContextCategory } from './types/api'

export interface ContextSegment {
  key: string
  label: string
  tokens: number
  color: string
  /** Percent of the bar, 0 to 100. */
  width: number
}

export interface ContextDetailRow {
  label: string
  tokens: number
}

export interface ContextRow {
  key: string
  label: string
  tokens: number
  color: string
  percentText: string
  /** Deferred rows: dimmed, no percent. */
  muted: boolean
  details: ContextDetailRow[] | null
}

/** Series colors, in order: the first ones go to the largest used categories. */
const PALETTE = [
  'var(--color-type-command)',
  'var(--color-secondary-soft)',
  'var(--color-type-file)',
  'var(--color-type-think)',
  'var(--color-type-agent)',
]
const OTHERS_COLOR = 'var(--color-fg-subtle)'
const BUFFER_COLOR = 'var(--color-line-strong)'
const TRACK_COLOR = 'var(--color-elevated)'
const MAX_SEGMENTS = 6

const percentFormat = new Intl.NumberFormat('pt-BR', { minimumFractionDigits: 1, maximumFractionDigits: 1 })

/** Category names as the CLI sends them; the detail lists attach to rows by these English names. */
const MCP_ROW = 'MCP tools'
const MCP_DEFERRED_ROW = 'MCP tools (deferred)'

function detailsFor(name: string, b: ContextBreakdown): ContextDetailRow[] | null {
  let list: ContextDetailRow[]
  switch (name) {
    case MCP_ROW:
      list = b.mcp_tools.filter((t) => t.loaded).map((t) => ({ label: `${t.server} · ${t.name}`, tokens: t.tokens }))
      break
    case MCP_DEFERRED_ROW:
      list = b.mcp_tools.filter((t) => !t.loaded).map((t) => ({ label: `${t.server} · ${t.name}`, tokens: t.tokens }))
      break
    case 'Skills':
      list = b.skills.map((s) => ({ label: s.name, tokens: s.tokens }))
      break
    case 'Memory files':
      list = b.memory_files.map((f) => ({ label: f.path, tokens: f.tokens }))
      break
    case 'Custom agents':
      list = b.agents.map((a) => ({ label: a.name, tokens: a.tokens }))
      break
    default:
      return null
  }
  return list.length ? list : null
}

/**
 * Stacked bar and list rows of a context breakdown, like the Desktop's: at most 6 segments. When the used
 * categories plus the buffer do not fit, the first `5 - extras` keep their own color and the rest becomes "Outros".
 */
export function contextLayout(b: ContextBreakdown): { segments: ContextSegment[]; rows: ContextRow[] } {
  const categories = b.categories.filter((c) => c.tokens > 0)
  const usedCats = categories.filter((c) => c.kind === 'used')
  const buffers = categories.filter((c) => c.kind === 'buffer')
  const extras = buffers.length ? 1 : 0

  // The palette has 5 colors: more than 5 used categories always group, even when 6 segments would fit.
  const grouped = usedCats.length + extras > MAX_SEGMENTS || usedCats.length > PALETTE.length
  const colored = grouped ? usedCats.slice(0, MAX_SEGMENTS - 1 - extras) : usedCats
  const rest = grouped ? usedCats.slice(colored.length) : []

  const segments: Omit<ContextSegment, 'width'>[] = colored.map((c, i) => ({
    key: `used:${c.name}`, label: c.name, tokens: c.tokens, color: PALETTE[i],
  }))
  if (rest.length) {
    segments.push({ key: 'others', label: 'Outros', tokens: rest.reduce((sum, c) => sum + c.tokens, 0), color: OTHERS_COLOR })
  }
  for (const c of buffers) segments.push({ key: `buffer:${c.name}`, label: c.name, tokens: c.tokens, color: BUFFER_COLOR })

  const freeTokens = categories.filter((c) => c.kind === 'free').reduce((sum, c) => sum + c.tokens, 0)
  const segmentTokens = segments.reduce((sum, s) => sum + s.tokens, 0)
  // Over the limit (no free space) the bar fills up to 100% instead of overflowing.
  const window = Math.max(b.max_tokens, segmentTokens + freeTokens)

  const colorOfUsed = new Map<ContextCategory, string>()
  colored.forEach((c, i) => colorOfUsed.set(c, PALETTE[i]))
  const rowColor = (c: ContextCategory): string => {
    if (c.kind === 'used') return colorOfUsed.get(c) ?? OTHERS_COLOR
    if (c.kind === 'buffer') return BUFFER_COLOR
    return TRACK_COLOR
  }
  // Percent over the model's raw window, like the header, so the numbers agree.
  const percentBase = b.max_tokens > 0 ? b.max_tokens : window

  return {
    segments: segments.map((s) => ({ ...s, width: window > 0 ? (s.tokens / window) * 100 : 0 })),
    rows: categories.map((c) => ({
      key: `${c.kind}:${c.name}`,
      label: c.kind === 'free' ? 'Espaço livre' : c.name,
      tokens: c.tokens,
      color: rowColor(c),
      percentText: c.kind === 'deferred' ? '—' : `${percentFormat.format((c.tokens / percentBase) * 100)}%`,
      muted: c.kind === 'deferred',
      details: c.kind === 'deferred' || c.kind === 'used' ? detailsFor(c.name, b) : null,
    })),
  }
}
