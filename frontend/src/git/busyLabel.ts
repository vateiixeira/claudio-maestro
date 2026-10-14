import type { GitOpKind, RepoDetails } from '../types/api'

const commits = (n: number) => (n === 1 ? '1 commit' : `${n} commits`)

/** What the wide button says while an action runs in the repository. */
export function busyLabel(kind: GitOpKind, repo: RepoDetails): string {
  switch (kind) {
    case 'stage': return 'Preparando…'
    case 'unstage': return 'Tirando da preparação…'
    case 'discard': return 'Descartando…'
    case 'commit': return 'Commitando…'
    case 'switch': return 'Trocando de branch…'
    case 'branch': return 'Criando branch…'
    case 'merge': return 'Mesclando…'
    case 'merge-abort': return 'Abortando o merge…'
    case 'merge-continue': return 'Concluindo o merge…'
    case 'resolve': return 'Marcando como resolvido…'
    case 'pull': return repo.behind ? `Baixando ${commits(repo.behind)}…` : 'Baixando…'
    case 'push': return 'Enviando…'
    case 'publish': return 'Publicando…'
    case 'sync': return 'Sincronizando…'
    case 'fetch-repo': return 'Buscando no remoto…'
  }
}
