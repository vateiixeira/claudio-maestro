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

/** The fields of the AGENT.md header with the values accepted (`backend/claudio_maestro/org/definition.py`). */
export const DEFINITION_FIELDS: { key: string; help: string }[] = [
  { key: 'name', help: 'obrigatório; o nome do agente na tela.' },
  { key: 'description', help: 'texto curto; aparece na árvore e diz aos outros agentes o que ele faz.' },
  { key: 'model', help: 'alias ou id do modelo (por exemplo sonnet, opus); vazio usa o padrão.' },
  { key: 'effort', help: 'low, medium, high, xhigh ou max; vazio usa o padrão.' },
  { key: 'permissionMode', help: 'default, acceptEdits, plan ou bypassPermissions (padrão).' },
  { key: 'disallowedTools', help: 'lista de ferramentas proibidas, como [Bash, WebFetch].' },
  { key: 'skills', help: 'lista de skills que o agente pode usar.' },
  { key: 'addDirs', help: 'lista de pastas extras; cada uma precisa estar dentro de um projeto registrado.' },
  { key: 'worktree', help: 'true ou false (padrão): trabalha numa worktree própria.' },
  { key: 'maxRunMinutes', help: 'número inteiro de minutos, de 1 em diante (padrão 120).' },
]
