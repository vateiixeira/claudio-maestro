/** Why the output sent to Claude is not the whole output of a command. */
export type NoteCode = 'truncated' | 'cleared' | 'input' | 'shell-exit' | 'empty'

/** The notes as the interface shows them (Claude gets the English ones from the backend). */
export const NOTE_TEXT: Record<NoteCode, string> = {
  truncated: 'Saída anterior cortada; só o fim foi enviado.',
  cleared: 'O comando limpou a tela; o que veio antes não foi enviado.',
  input: 'Você digitou no terminal durante o comando; a saída depois disso não foi enviada.',
  'shell-exit': 'O shell saiu antes de o comando terminar.',
  empty: 'Sem saída.',
}

const ATTACH_HEADER = '<!-- attach: Terminal -->'

/**
 * The message text for terminal snippets attached to a turn: one quoted block per
 * snippet (`> ` before each line, an empty line stays `> `), then the user's text.
 */
export function formatTerminalAttachments(snippets: string[], text: string): string {
  if (snippets.length === 0) return text
  const blocks = snippets.map((snippet) => {
    const lines = snippet.replace(/\r\n?/g, '\n').split('\n').map((line) => `> ${line}`)
    return `${ATTACH_HEADER}\n${lines.join('\n')}`
  })
  const body = blocks.join('\n\n')
  return text.trim() ? `${body}\n\n${text}` : body
}

/** "320 ms" under a second; from there one decimal with a comma ("1,9 s"). */
export function formatDuration(ms: number): string {
  if (ms < 1000) return `${Math.max(0, Math.round(ms))} ms`
  return `${(ms / 1000).toFixed(1).replace('.', ',')} s`
}
