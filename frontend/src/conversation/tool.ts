// Images a tool returned arrive as a marker (`omitted: true`, `index`); toolImages.ts loads the bytes.
export const RENDERABLE_IMAGE_TYPES: ReadonlySet<string> = new Set(['image/png', 'image/jpeg', 'image/gif', 'image/webp'])

export interface ToolImageRef {
  /** Position among the images of that result. */
  index: number
  mediaType: string
  size: number | null
}

/** The marker as a renderable image, or null (an old marker without `index`, or a type the backend refuses). */
export function toolImageRef(block: unknown): ToolImageRef | null {
  if (!block || typeof block !== 'object') return null
  const b = block as Record<string, unknown>
  if (b.type !== 'image' || b.omitted !== true) return null
  if (typeof b.index !== 'number' || !Number.isInteger(b.index) || b.index < 0) return null
  if (typeof b.media_type !== 'string' || !RENDERABLE_IMAGE_TYPES.has(b.media_type)) return null
  return { index: b.index, mediaType: b.media_type, size: typeof b.size === 'number' ? b.size : null }
}

/** Text of a tool result `content`: a string, or a list of blocks with `text`. */
export function resultText(content: unknown): string {
  if (content == null) return ''
  if (typeof content === 'string') return content
  if (Array.isArray(content)) {
    return content
      .map((block) => {
        if (block && typeof block === 'object' && 'text' in block) return String(block.text)
        if (block && typeof block === 'object' && block.type === 'image' && block.omitted) {
          // A renderable image shows in the strip of thumbnails: no text for it.
          return toolImageRef(block) ? null : '[Imagem omitida]'
        }
        return JSON.stringify(block, null, 2)
      })
      .filter((text): text is string => text !== null)
      .join('\n')
  }
  return JSON.stringify(content, null, 2)
}

export function prettyJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2) ?? ''
  } catch {
    return String(value)
  }
}

export function countLines(text: string): number {
  if (!text) return 0
  return text.replace(/\n$/, '').split('\n').length
}

export function str(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

/**
 * The model an Agent call asked for, as the fallback until the subagent's own messages name the
 * real one. "inherit" (the default) says nothing, so it gives null.
 */
export function askedModel(input: Record<string, unknown>): string | null {
  const model = str(input.model).trim()
  return model && model.toLowerCase() !== 'inherit' ? model : null
}

/** "servidor · ferramenta" for MCP tools (`mcp__server__tool`); other names unchanged. */
export function toolLabel(name: string): string {
  const match = /^mcp__(.+?)__(.+)$/.exec(name)
  return match ? `${match[1]} · ${match[2]}` : name
}

/** The URL when it is http or https, else null (never a `javascript:` link). */
export function safeHttpUrl(value: string): string | null {
  try {
    const url = new URL(value)
    return url.protocol === 'http:' || url.protocol === 'https:' ? url.href : null
  } catch {
    return null
  }
}
