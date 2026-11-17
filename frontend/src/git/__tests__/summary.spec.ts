import { describe, expect, it } from 'vitest'
import { gitTotals, summaryParts } from '../summary'
import { makeGitRepo } from '../../test/factories'

const repos = [
  makeGitRepo({ path: '/r/a', ahead: 23, behind: 0 }),
  makeGitRepo({ path: '/r/b', ahead: 7, behind: 2 }),
  makeGitRepo({ path: '/r/c', ahead: 3, behind: 0 }),
  makeGitRepo({ path: '/r/d', upstream: null, ahead: null, behind: null, changed: { staged: 0, unstaged: 0, untracked: 1 } }),
  makeGitRepo({ path: '/r/e', upstream: null, ahead: null, behind: null }),
  makeGitRepo({ path: '/r/f', error: 'falhou', ahead: 9, changed: { staged: 4, unstaged: 0, untracked: 0 } }),
]

describe('gitTotals', () => {
  it('soma os totais; repositório com erro conta só em errors', () => {
    expect(gitTotals(repos)).toEqual({ ahead: 33, aheadRepos: 3, behind: 2, noUpstream: 2, changes: 1, errors: 1 })
  })

  it('HEAD destacado sem upstream não conta como sem upstream', () => {
    expect(gitTotals([makeGitRepo({ detached: true, branch: null, upstream: null, ahead: null, behind: null })]).noUpstream).toBe(0)
  })
})

describe('summaryParts', () => {
  it('lista as partes não nulas, na ordem', () => {
    expect(summaryParts(gitTotals(repos)).map((p) => p.text)).toEqual([
      '33 commits para enviar em 3 repositórios', '2 para baixar', '2 sem upstream', '1 alteração', '1 com erro',
    ])
    expect(summaryParts(gitTotals(repos)).map((p) => p.part)).toEqual(['ahead', 'behind', 'no-upstream', 'changes', 'errors'])
  })

  it('singular e plural', () => {
    expect(summaryParts({ ahead: 1, aheadRepos: 1, behind: 0, noUpstream: 0, changes: 3, errors: 0 }).map((p) => p.text))
      .toEqual(['1 commit para enviar em 1 repositório', '3 alterações'])
  })

  it('sem nada: Tudo em dia', () => {
    expect(summaryParts({ ahead: 0, aheadRepos: 0, behind: 0, noUpstream: 0, changes: 0, errors: 0 }))
      .toEqual([{ part: 'clear', text: 'Tudo em dia' }])
  })
})
