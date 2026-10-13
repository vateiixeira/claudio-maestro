import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { flushPromises } from '@vue/test-utils'
import { useGitLogStore } from '../gitLog'
import { jsonResponse, logUrl, makeLogCommit, makeRepoLog, routeFetch } from '../../test/factories'

const REPO = '/home/vi/dev/loja/api'
const commits = (from: number, count: number) =>
  Array.from({ length: count }, (_, i) => makeLogCommit({ full_hash: `${String(from + i).padStart(7, '0')}${'a'.repeat(33)}`, subject: `c${from + i}` }))

beforeEach(() => setActivePinia(createPinia()))
afterEach(() => vi.unstubAllGlobals())

describe('gitLog', () => {
  it('carrega a primeira página e depois mais', async () => {
    const fetchMock = routeFetch({
      [logUrl(1, REPO)]: () => jsonResponse(makeRepoLog({ commits: commits(0, 30), has_more: true })),
      [logUrl(1, REPO, 30)]: () => jsonResponse(makeRepoLog({ commits: commits(30, 5), has_more: false })),
    })
    vi.stubGlobal('fetch', fetchMock)
    const store = useGitLogStore()
    await store.load(1, REPO)
    expect(store.logFor(1, REPO)?.commits).toHaveLength(30)
    await store.loadMore(1, REPO)
    expect(store.logFor(1, REPO)?.commits).toHaveLength(35)
    expect(store.logFor(1, REPO)?.hasMore).toBe(false)
  })

  it('troca de branch sem checkout e mantém a escolha ao atualizar', async () => {
    const fetchMock = routeFetch({
      [logUrl(1, REPO)]: () => jsonResponse(makeRepoLog({ commits: commits(0, 2) })),
      [logUrl(1, REPO, 0, 'refs/heads/feat')]: () => jsonResponse(makeRepoLog({ ref: 'refs/heads/feat', branch: 'feat', commits: commits(10, 1) })),
      [logUrl(1, REPO, 0, 'refs/heads/feat', 30)]: () => jsonResponse(makeRepoLog({ ref: 'refs/heads/feat', branch: 'feat', commits: commits(10, 2) })),
    })
    vi.stubGlobal('fetch', fetchMock)
    const store = useGitLogStore()
    await store.load(1, REPO)
    await store.setRef(1, REPO, 'refs/heads/feat')
    expect(store.logFor(1, REPO)?.branch).toBe('feat')
    await store.refresh(1, REPO)
    expect(store.logFor(1, REPO)?.commits).toHaveLength(2)
    expect(fetchMock.mock.calls.every(([url]) => !String(url).includes('checkout'))).toBe(true)
  })

  it('descarta a resposta de uma carga antiga', async () => {
    let release!: () => void
    const slow = new Promise<Response>((resolve) => { release = () => resolve(jsonResponse(makeRepoLog({ commits: commits(0, 1) }))) })
    vi.stubGlobal('fetch', routeFetch({
      [logUrl(1, REPO)]: () => slow,
      [logUrl(1, REPO, 0, 'refs/heads/feat')]: () => jsonResponse(makeRepoLog({ branch: 'feat', commits: commits(5, 3) })),
    }))
    const store = useGitLogStore()
    void store.load(1, REPO)
    await store.setRef(1, REPO, 'refs/heads/feat')
    release()
    await flushPromises()
    expect(store.logFor(1, REPO)?.branch).toBe('feat')
    expect(store.logFor(1, REPO)?.commits).toHaveLength(3)
  })

  it('guarda erro e guarda em cache o commit e o diff', async () => {
    const sha = 'abc1234abc1234abc1234abc1234abc1234abc12'
    const fetchMock = routeFetch({
      [logUrl(1, REPO)]: () => jsonResponse({ detail: 'O git falhou.' }, 502),
      [`GET /api/projects/1/git/commit?${new URLSearchParams({ repo: REPO, sha })}`]: () => jsonResponse({ ...makeLogCommit(), files: [], files_truncated: false }),
      [`GET /api/projects/1/git/commit/diff?${new URLSearchParams({ repo: REPO, sha, file: 'a.txt' })}`]: () => jsonResponse({ diff: '+x', truncated: false }),
    })
    vi.stubGlobal('fetch', fetchMock)
    const store = useGitLogStore()
    await store.load(1, REPO)
    expect(store.logFor(1, REPO)?.error).toBe('O git falhou.')
    await store.commit(1, REPO, sha)
    await store.commit(1, REPO, sha)
    await store.commitDiff(1, REPO, sha, 'a.txt')
    await store.commitDiff(1, REPO, sha, 'a.txt')
    expect(fetchMock.mock.calls.filter(([url]) => String(url).includes('/git/commit')).length).toBe(2)
  })
})
