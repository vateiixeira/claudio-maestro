// Small helpers of the agent panel.

const thousands = new Intl.NumberFormat('pt-BR')
export const formatCount = (n: number) => thousands.format(n)

const encoder = new TextEncoder()
/** Size of a text in UTF-8 bytes, which is what the limit of the AGENT.md counts. */
export const byteLength = (text: string) => encoder.encode(text).length

/** Only http and https become links; anything else (a `javascript:` URL, a path) stays text. */
export function safeLink(link: string | null): string | null {
  if (!link) return null
  try {
    const url = new URL(link)
    return url.protocol === 'http:' || url.protocol === 'https:' ? url.href : null
  } catch {
    return null
  }
}

/** What the panel keeps of an AGENT.md being edited: the text and the hash of the file it was based on. */
export interface DefinitionDraft {
  text: string
  hash: string | null
}

/** The fields of the AGENT.md header with the values accepted (`backend/claudio_maestro/org/definition.py`). `fallback` is what the agent uses when the field is absent. */
export const DEFINITION_FIELDS: { key: string; help: string; fallback: string | null }[] = [
  { key: 'name', help: 'obrigatório; o nome do agente na tela.', fallback: null },
  { key: 'description', help: 'texto curto; aparece na árvore e diz aos outros agentes o que ele faz.', fallback: null },
  { key: 'model', help: 'alias ou id do modelo (por exemplo sonnet, opus); vazio usa o padrão.', fallback: 'padrão' },
  { key: 'effort', help: 'low, medium, high, xhigh ou max; vazio usa o padrão.', fallback: 'padrão' },
  { key: 'permissionMode', help: 'default, acceptEdits, plan ou bypassPermissions (padrão).', fallback: 'padrão: bypassPermissions' },
  { key: 'disallowedTools', help: 'lista de ferramentas proibidas, como [Bash, WebFetch].', fallback: 'nenhuma' },
  { key: 'skills', help: 'lista de skills que o agente pode usar.', fallback: 'nenhuma' },
  { key: 'addDirs', help: 'lista de pastas extras; cada uma precisa estar dentro de um projeto registrado.', fallback: 'nenhuma' },
  { key: 'worktree', help: 'true ou false (padrão): trabalha numa worktree própria.', fallback: 'padrão: false' },
  { key: 'maxRunMinutes', help: 'número inteiro de minutos, de 1 em diante (padrão 120).', fallback: 'padrão: 120' },
]

const unquote = (value: string) => value.replace(/^(["'])(.*)\1$/, '$2')

/**
 * Reads the header of an AGENT.md (between the `---` lines): first-level `key: value` pairs, `[a, b]` lists and block lists
 * (`- item`). Quotes are removed and the rest is ignored. Null when the text has no header.
 */
export function parseHeader(text: string): Record<string, string | string[]> | null {
  const lines = text.split(/\r?\n/)
  if (lines[0]?.trim() !== '---') return null
  const result: Record<string, string | string[]> = {}
  let blockKey: string | null = null
  for (const line of lines.slice(1)) {
    if (line.trim() === '---') break
    const item = /^\s+-\s+(.*)$/.exec(line)
    if (item && blockKey) {
      const list = result[blockKey]
      const value = unquote(item[1]!.trim())
      result[blockKey] = Array.isArray(list) ? [...list, value] : [value]
      continue
    }
    const pair = /^([A-Za-z_][\w-]*):\s*(.*)$/.exec(line)
    if (!pair) continue
    const key = pair[1]!
    const raw = pair[2]!.trim()
    if (raw.startsWith('[') && raw.endsWith(']')) {
      result[key] = raw.slice(1, -1).split(',').map((part) => unquote(part.trim())).filter(Boolean)
      blockKey = null
    } else {
      result[key] = unquote(raw)
      blockKey = raw === '' ? key : null
    }
  }
  return result
}

const baseName = (path: string) => path.replace(/[\\/]+$/, '').split(/[\\/]/).pop() ?? path

/** A header value written for reading: "3 pastas: a, b, c" for addDirs, a comma list for the others, "nenhuma" for an empty list. */
export function fieldValue(key: string, value: string | string[]): string {
  if (!Array.isArray(value)) return value
  if (value.length === 0) return 'nenhuma'
  if (key === 'addDirs') return `${value.length} ${value.length === 1 ? 'pasta' : 'pastas'}: ${value.map(baseName).join(', ')}`
  return value.join(', ')
}

/** A status of the registry (`pr-aberto`, `em_analise`) written for reading: "PR aberto", "Em analise". */
export function registryStatusLabel(status: string): string {
  const words = status.trim().replace(/[-_]+/g, ' ').split(/\s+/).filter(Boolean)
  if (words.length === 0) return ''
  if (words[0]!.toLowerCase() === 'pr') words[0] = 'PR'
  const text = words.join(' ')
  return text.charAt(0).toUpperCase() + text.slice(1)
}

export type RegistryTone = 'waiting' | 'info' | 'muted' | 'neutral'

/** How a status of the registry is drawn: waiting for you, in progress, set aside, or nothing special. */
export function registryTone(status: string): RegistryTone {
  const s = status.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/[-_]+/g, ' ').trim()
  if (s.startsWith('aguard') || s.startsWith('pendent')) return 'waiting'
  if (s === 'pr' || s.startsWith('pr ') || s.startsWith('aberto')) return 'info'
  if (s.startsWith('descart') || s.startsWith('ignor') || s.startsWith('ruido')) return 'muted'
  return 'neutral'
}

/** A short name for a link of the registry: "repo · PR #12", "repo · #7" or the host. Null for anything that is not http(s). */
export function linkLabel(url: string): string | null {
  const href = safeLink(url)
  if (!href) return null
  const parsed = new URL(href)
  const host = parsed.hostname.replace(/^www\./, '')
  if (host === 'github.com') {
    const match = /^\/[^/]+\/([^/]+)\/(pull|issues)\/(\d+)/.exec(parsed.pathname)
    if (match) return `${match[1]} · ${match[2] === 'pull' ? 'PR ' : ''}#${match[3]}`
  }
  return host
}

export type MemoryLevel = 'ok' | 'near' | 'over'

/** How full the memory is: `near` from 90% of the limit, `over` above it. */
export function memoryLevel(length: number, max: number): MemoryLevel {
  if (length > max) return 'over'
  return length * 10 >= max * 9 ? 'near' : 'ok'
}
