import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { branchText, repoLabel, useGitStore } from '../git'
import { jsonResponse, makeGitRepo, routeFetch } from '../../test/factories'
import { diffFromUnified } from '../../conversation/diff'

beforeEach(() => setActivePinia(createPinia()))
afterEach(() => vi.unstubAllGlobals())

describe('store git', () => {
  it('carrega os repositórios do projeto', async () => {
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/projects/1/git': () => jsonResponse({ repos: [makeGitRepo({ branch: 'main' })] }),
    }))
    const git = useGitStore()
    await git.load(1)
    expect(git.reposFor(1).map((r) => r.branch)).toEqual(['main'])
    expect(git.isLoaded(1)).toBe(true)
  })

  it('aplica o evento project.git', () => {
    const git = useGitStore()
    git.applyEvent({ session_id: null, seq: 0, type: 'project.git', data: { project_id: 2, repos: [makeGitRepo({ branch: 'feat/x' })] } } as never)
    expect(git.reposFor(2)[0]!.branch).toBe('feat/x')
  })

  it('erro ao carregar não lança em ensure', async () => {
    vi.stubGlobal('fetch', routeFetch({}))
    const git = useGitStore()
    git.ensure(3)
    await flushPromises()
    expect(git.reposFor(3)).toEqual([])
  })
})

describe('textos de branch', () => {
  it('branch, HEAD solto e erro', () => {
    expect(branchText(makeGitRepo({ branch: 'main' }))).toBe('main')
    expect(branchText(makeGitRepo({ branch: null, detached: true, head: 'abc1234' }))).toBe('HEAD solto · abc1234')
    expect(branchText(makeGitRepo({ branch: null, error: 'falhou' }))).toBe('branch indisponível')
  })

  it('rótulo com o repositório só quando não é a raiz', () => {
    expect(repoLabel(makeGitRepo({ rel_path: '.', branch: 'main' }))).toBe('main')
    expect(repoLabel(makeGitRepo({ rel_path: 'api', branch: 'feat/x' }))).toBe('api · feat/x')
  })
})

describe('diff unificado', () => {
  it('lê hunks com números de linha', () => {
    const lines = diffFromUnified('diff --git a/x b/x\n--- a/x\n+++ b/x\n@@ -1,2 +1,2 @@\n a\n-b\n+c\n')
    expect(lines).toEqual([
      { kind: 'context', oldNo: 1, newNo: 1, text: 'a' },
      { kind: 'del', oldNo: 2, newNo: null, text: 'b' },
      { kind: 'add', oldNo: null, newNo: 2, text: 'c' },
    ])
  })
})
