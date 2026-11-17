import { describe, expect, it } from 'vitest'
import { isPending, pendingCount } from '../pending'
import { makeGitRepo, makeRepoDetails, makeRepoState } from '../../test/factories'

describe('isPending', () => {
  it('repositório em dia não é pendência', () => {
    expect(isPending(makeRepoDetails({ upstream: 'origin/main', ahead: 0, behind: 0 }))).toBe(false)
  })

  it('alterações, commits a enviar ou baixar e erro são pendências', () => {
    expect(isPending(makeRepoDetails({ changed: { staged: 0, unstaged: 0, untracked: 1 } }))).toBe(true)
    expect(isPending(makeRepoDetails({ upstream: 'origin/main', ahead: 1, behind: 0 }))).toBe(true)
    expect(isPending(makeRepoDetails({ upstream: 'origin/main', ahead: 0, behind: 1 }))).toBe(true)
    expect(isPending(makeRepoDetails({ error: 'falhou' }))).toBe(true)
  })

  it('sem upstream não é pendência', () => {
    expect(isPending(makeRepoDetails({ upstream: null, ahead: null, behind: null }))).toBe(false)
  })

  it('merge em andamento e arquivos listados são pendências', () => {
    expect(isPending(makeRepoDetails({ state: makeRepoState({ merging: true }) }))).toBe(true)
    expect(isPending(makeRepoDetails({ files: [{ path: 'a', status: 'unstaged', added: 1, removed: 0 }] }))).toBe(true)
  })

  it('aceita o resumo, sem files nem state', () => {
    expect(isPending(makeGitRepo())).toBe(false)
    expect(isPending(makeGitRepo({ ahead: 2 }))).toBe(true)
  })
})

describe('pendingCount', () => {
  it('conta só os repositórios pendentes', () => {
    const limpo = makeRepoDetails()
    const comAlteracao = makeRepoDetails({ changed: { staged: 1, unstaged: 0, untracked: 0 } })
    const comErro = makeRepoDetails({ error: 'falhou' })
    expect(pendingCount([limpo, comAlteracao, comErro])).toBe(2)
    expect(pendingCount([])).toBe(0)
  })
})
