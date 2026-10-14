import type { RepoDetails } from '../types/api'

/** What "Pedir ao Claude para resolver" sends to the new session. */
export function conflictPrompt(repo: RepoDetails, repoName: string): string {
  const state = repo.state
  const incoming = state?.merge_branch ?? 'a outra branch'
  const current = repo.branch ?? repo.head ?? 'a branch atual'
  const files = (state?.conflicts ?? []).map((path) => `- ${path}`).join('\n')
  return [
    `No repositório ${repo.path} (${repoName}), o merge de ${incoming} em ${current} parou com conflito nestes arquivos:`,
    '',
    files,
    '',
    'Resolva cada conflito mantendo o que as duas branches querem fazer e tire as marcas <<<<<<<, ======= e >>>>>>>. Se o projeto tiver testes, rode os que cobrem esses arquivos.',
    'Não faça commit, não rode git add e não aborte o merge: eu reviso, marco os arquivos como resolvidos e concluo o merge pelo Maestro.',
  ].join('\n')
}
