/** Text of a tool result `content`: a string, or a list of blocks with `text`. */
export function resultText(content: unknown): string {
  if (content == null) return ''
  if (typeof content === 'string') return content
  if (Array.isArray(content)) {
    return content
      .map((block) => (block && typeof block === 'object' && 'text' in block ? String(block.text) : JSON.stringify(block, null, 2)))
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
