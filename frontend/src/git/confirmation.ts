import type { Session } from '../types/api'

export interface ConfirmationFile {
  path: string
  kind: string
  added: number | null
  removed: number | null
  untracked: boolean
}

/** What a confirmation dialog of the Git panel shows. */
export interface Confirmation {
  title: string
  confirmLabel: string
  tone: 'danger' | 'warn' | 'primary'
  /** A session running in the repository; the dialog names it. */
  running: Session | null
  repoName: string
  /** Paragraphs of explanation, in order. */
  lines: string[]
  /** The one file being discarded. */
  file?: ConfirmationFile
}

/** What happens to a running session, by action. */
export function runningLine(action: 'switch' | 'merge' | 'pull' | 'sync' | 'discard'): string {
  switch (action) {
    case 'switch': return 'Trocar de branch agora muda os arquivos que a sessão está lendo e editando. O que ela fizer depois vai cair na branch nova.'
    case 'merge': return 'Mesclar agora muda os arquivos que a sessão está lendo e editando.'
    case 'pull':
    case 'sync': return 'Baixar agora muda os arquivos que a sessão está lendo e editando.'
    case 'discard': return 'Descartar agora apaga alterações que a sessão pode estar usando.'
  }
}
