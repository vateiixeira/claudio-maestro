import type { RepoDetails } from '../types/api'

export type PrimaryKind = 'merge-continue' | 'commit' | 'publish' | 'sync' | 'push' | 'pull'

export interface PrimaryAction {
  kind: PrimaryKind
  label: string
  disabled: boolean
  /** Why it is off, for the button's title; null when it is on. */
  reason: string | null
  /** Remote that "Publicar" pushes to. */
  remote?: string
}

const NO_MESSAGE = 'Escreva a mensagem do commit'
const MANY_REMOTES = 'Há vários remotos e nenhum se chama origin. Publique esta branch pelo terminal.'

const commits = (n: number) => (n === 1 ? '1 commit' : `${n} commits`)

/** `origin` when there is one, else the only remote; null with none or several. */
export function publishRemote(remotes: string[]): string | null {
  if (remotes.includes('origin')) return 'origin'
  return remotes.length === 1 ? remotes[0] : null
}

/** The wide button of a repository: the first rule of the spec that holds. */
export function primaryAction(repo: RepoDetails, message: string): PrimaryAction {
  const state = repo.state ?? null
  const empty = message.trim() === ''
  const messageReason = empty ? NO_MESSAGE : null

  if (state?.merging) {
    const left = state.conflicts.length
    if (left > 0) {
      return {
        kind: 'merge-continue', label: `Concluir merge (falta resolver ${left})`, disabled: true,
        reason: left === 1 ? 'Falta resolver 1 arquivo' : `Falta resolver ${left} arquivos`,
      }
    }
    return { kind: 'merge-continue', label: 'Concluir merge', disabled: empty, reason: messageReason }
  }

  const staged = new Set(repo.files.filter((f) => f.status === 'staged').map((f) => f.path)).size
  if (staged > 0) {
    const label = staged === 1 ? 'Commitar 1 preparado' : `Commitar ${staged} preparados`
    return { kind: 'commit', label, disabled: empty, reason: messageReason }
  }
  if (repo.files.length > 0) return { kind: 'commit', label: 'Commitar', disabled: empty, reason: messageReason }

  const remotes = state?.remotes ?? []
  if (repo.upstream == null && !repo.detached && repo.branch && repo.head && remotes.length > 0) {
    const remote = publishRemote(remotes)
    if (remote) return { kind: 'publish', label: `Publicar branch em ${remote}`, disabled: false, reason: null, remote }
    return { kind: 'publish', label: 'Publicar branch', disabled: true, reason: MANY_REMOTES }
  }

  if (repo.upstream != null) {
    const ahead = repo.ahead ?? 0
    const behind = repo.behind ?? 0
    const noMerge = state?.no_merge ?? null
    if (behind > 0 && ahead > 0) return { kind: 'sync', label: `Sincronizar ${behind}↓ ${ahead}↑`, disabled: noMerge != null, reason: noMerge }
    if (ahead > 0) return { kind: 'push', label: `Enviar ${commits(ahead)}`, disabled: false, reason: null }
    if (behind > 0) return { kind: 'pull', label: `Baixar ${commits(behind)}`, disabled: noMerge != null, reason: noMerge }
  }
  return { kind: 'commit', label: 'Commitar', disabled: true, reason: 'Não há alterações para commitar' }
}
