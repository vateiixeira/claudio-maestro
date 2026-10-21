import type { RunState } from '../stores/terminal'

/** Fence languages whose code is a shell command the play button may run. */
export const SHELL_LANGS = ['bash', 'sh', 'shell', 'zsh', 'console', 'terminal']

// A block with no language only gets a play button when it reads like a command.
const UNTAGGED_START = /^(?:\$ |(?:sudo|cd|ls|git|uv|pnpm|npm|node|python3?|pip|docker|ssh|scp|curl|wget|make|cat|grep|rg|find|export|systemctl|journalctl|kill|ps|echo|mkdir|rm|cp|mv|chmod|tail|head)\b)/
const UNTAGGED_MAX_LINES = 10

/**
 * The command a fenced block would run, or `null` when it is not a command.
 * `lang` is the first word of the fence info; `code` is the block text.
 */
export function commandFromBlock(lang: string, code: string): string | null {
  const name = lang.trim().toLowerCase()
  if (name !== '' && !SHELL_LANGS.includes(name)) return null
  const lines = code.split('\n')
  if (name === '') {
    const filled = lines.filter((line) => line.trim() !== '')
    if (filled.length === 0 || filled.length > UNTAGGED_MAX_LINES) return null
    if (!UNTAGGED_START.test(filled[0]!.trimStart())) return null
  }
  if (name === 'console' || lines.some((line) => line.startsWith('$ '))) {
    const commands = lines.filter((line) => line.startsWith('$ ')).map((line) => line.slice(2))
    const command = commands.join('\n').trim()
    return command === '' ? null : command
  }
  const command = code.trim()
  return command === '' ? null : command
}

/** The text of a play button for the state of its run. */
export function runLabel(state: RunState | 'idle', exitCode: number | null): string {
  switch (state) {
    case 'starting':
    case 'running':
      return 'Rodando…'
    case 'sent':
      return exitCode === null ? 'Enviado' : `Enviado · código ${exitCode}`
    case 'interrupted':
      return 'Interrompido'
    case 'failed':
      return 'Não foi possível enviar'
    case 'busy':
      return 'O terminal está ocupado'
    default:
      return 'Rodar'
  }
}

/** The play button's own `aria-label` while it is idle. */
const IDLE_ARIA = 'Rodar no terminal'

export interface RunSnapshot { state: RunState; exitCode: number | null }

/** Key of a block's run: the message and the block's position among all the fenced blocks of the message. */
export const blockKeyFor = (itemId: string, index: number): string => `${itemId}:${index}`

/**
 * Delegated click handler for the play buttons that `renderMarkdown` puts in command blocks.
 * `event.currentTarget` is the element that holds the rendered blocks.
 */
export function onCodeRunClick(
  event: MouseEvent,
  itemId: string,
  run: (command: string, blockKey: string) => void,
): void {
  const target = event.target
  const root = event.currentTarget
  if (!(target instanceof Element) || !(root instanceof Element)) return
  const button = target.closest('[data-code-run]')
  const block = button?.closest<HTMLElement>('.code-block')
  if (!button || !block) return
  const code = block.querySelector('pre code')?.textContent
  if (code == null) return
  const command = commandFromBlock(block.dataset.lang ?? '', code)
  if (command === null) return
  const index = Array.from(root.querySelectorAll('.code-block')).indexOf(block)
  if (index < 0) return
  run(command, blockKeyFor(itemId, index))
}

/** Puts each block's run state on the DOM: `data-run-state` on the block and the label on its play button. */
export function applyRunStates(root: Element, itemId: string, runs: Record<string, RunSnapshot | undefined>): void {
  root.querySelectorAll<HTMLElement>('.code-block').forEach((block, index) => {
    const button = block.querySelector<HTMLElement>('[data-code-run]')
    if (!button) return
    const info = runs[blockKeyFor(itemId, index)]
    const state = info?.state ?? 'idle'
    const text = runLabel(state, info?.exitCode ?? null)
    block.dataset.runState = state
    const span = button.querySelector('span')
    if (span && span.textContent !== text) span.textContent = text
    button.setAttribute('aria-label', state === 'idle' ? IDLE_ARIA : text)
  })
}
