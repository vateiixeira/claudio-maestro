import type { RepoFile } from '../types/api'

/** The change of a file in words: "novo", "modificado", "apagado", "renomeado" or "em conflito". */
export function fileStatusText(file: RepoFile): string {
  if (file.status === 'conflict' || file.kind === 'U') return 'em conflito'
  if (file.status === 'untracked' || file.kind === 'A') return 'novo'
  if (file.kind === 'D') return 'apagado'
  if (file.kind === 'R') return 'renomeado'
  return 'modificado'
}
