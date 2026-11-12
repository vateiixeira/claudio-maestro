import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { flushPromises } from '@vue/test-utils'
import { useGitLogStore } from '../gitLog'
import { useProjectsStore } from '../projects'
import { jsonResponse, makeLogCommit, makeRepoLog } from '../../test/factories'

const REPO = '/repo'
const HEAD = 'a'.repeat(40)
const UPSTREAM = 'b'.repeat(40)
const rows = (start: number, count: number) => Array.from({ length: count }, (_, index) => makeLogCommit({ full_hash: (start + index).toString(16).padStart(40, '0') }))
const page = (start: number, count: number, more = false) => ({ ...makeRepoLog(), head_sha: HEAD, upstream_sha: UPSTREAM, next_skip: more ? start + count : null, commits: rows(start, count), has_more: more })
beforeEach(() => setActivePinia(createPinia()))
afterEach(() => vi.unstubAllGlobals())

describe('histórico por snapshot', () => {
  it('mantém nomes do snapshot quando o checkout muda entre páginas', async () => {
    let changed = false
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({
      ...page(changed ? 30 : 0, 30, true), branch: changed ? 'feature' : 'main',
      upstream: changed ? 'origin/feature' : 'origin/main',
    })))
    const store = useGitLogStore()
    await store.load(1, REPO)
    changed = true
    await store.loadMore(1, REPO)
    await store.loadDirection(1, REPO, 'incoming')
    expect(store.logFor(1, REPO)?.branch).toBe('main')
    expect(store.logFor(1, REPO)?.upstream).toBe('origin/main')
    expect(store.logFor(1, REPO, 'incoming')?.branch).toBe('main')
    expect(store.logFor(1, REPO, 'incoming')?.upstream).toBe('origin/main')
    await store.refresh(1, REPO)
    expect(store.logFor(1, REPO)?.updateAvailable).toBe(true)
  })

  it('fixa os dois SHAs ao carregar páginas seguintes, inclusive sem upstream', async () => {
    const fetch = vi.fn(async (_url: string) => jsonResponse(page(0, 30, true)))
    vi.stubGlobal('fetch', fetch)
    const store = useGitLogStore()
    await store.load(1, REPO)
    await store.loadMore(1, REPO)
    const query = new URL(String(fetch.mock.calls[1]![0]), 'http://localhost').searchParams
    expect(query.get('snapshot_head')).toBe(HEAD)
    expect(query.get('snapshot_upstream')).toBe(UPSTREAM)
    expect(query.get('include_incoming')).toBe('false')
    fetch.mockImplementation(async () => jsonResponse({ ...page(0, 30, true), upstream_sha: null }))
    await store.load(2, REPO)
    await store.loadMore(2, REPO)
    expect(new URL(String(fetch.mock.calls.at(-1)![0]), 'http://localhost').searchParams.get('snapshot_upstream')).toBe('-')
  })

  it('mantém mais de 300 itens e sinaliza novo snapshot sem substituir a leitura', async () => {
    let changed = false
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      const query = new URL(url, 'http://localhost').searchParams
      const skip = Number(query.get('skip'))
      return jsonResponse({ ...page(skip, 30, true), head_sha: query.get('snapshot_head') ?? (changed ? 'c'.repeat(40) : HEAD) })
    }))
    const store = useGitLogStore()
    await store.load(1, REPO)
    for (let i = 0; i < 10; i++) await store.loadMore(1, REPO)
    await store.refresh(1, REPO)
    expect(store.logFor(1, REPO)?.commits).toHaveLength(330)
    changed = true
    await store.refresh(1, REPO)
    expect(store.logFor(1, REPO)?.commits).toHaveLength(330)
    expect(store.logFor(1, REPO)?.updateAvailable).toBe(true)
    expect(store.logFor(1, REPO)?.headSha).toBe(HEAD)
    await store.loadMore(1, REPO)
    expect(store.logFor(1, REPO)?.updateAvailable).toBe(true)
    await store.load(1, REPO)
    expect(store.logFor(1, REPO)?.headSha).toBe('c'.repeat(40))
    expect(store.logFor(1, REPO)?.updateAvailable).toBe(false)
  })

  it('pagina incoming e outgoing separadamente no mesmo snapshot', async () => {
    const fetch = vi.fn(async (url: string) => {
      const query = new URL(url, 'http://localhost').searchParams
      const skip = Number(query.get('skip'))
      return jsonResponse({ ...page(skip, 30, true), direction: query.get('direction') ?? 'all' })
    })
    vi.stubGlobal('fetch', fetch)
    const store = useGitLogStore()
    await store.load(1, REPO)
    await store.loadDirection(1, REPO, 'incoming')
    await store.loadMore(1, REPO, 'incoming')
    await store.loadDirection(1, REPO, 'outgoing')
    expect(store.logFor(1, REPO)?.commits).toHaveLength(30)
    expect(store.logFor(1, REPO, 'incoming')?.commits).toHaveLength(60)
    expect(store.logFor(1, REPO, 'outgoing')?.commits).toHaveLength(30)
    const query = new URL(String(fetch.mock.calls[1]![0]), 'http://localhost').searchParams
    expect(query.get('snapshot_head')).toBe(HEAD)
    expect(query.get('snapshot_upstream')).toBe(UPSTREAM)
  })

  it('invalida uma direção pendente quando a referência muda', async () => {
    let release!: (response: Response) => void
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (new URL(url, 'http://localhost').searchParams.get('direction')) return new Promise<Response>((resolve) => { release = resolve })
      return jsonResponse(page(0, 1))
    }))
    const store = useGitLogStore()
    await store.load(1, REPO)
    void store.loadDirection(1, REPO, 'incoming')
    await store.setRef(1, REPO, 'refs/heads/next')
    release(jsonResponse(page(10, 3)))
    await flushPromises()
    expect(store.logFor(1, REPO, 'incoming')).toBeNull()
  })

  it('limita cache e reutiliza a entrada acessada recentemente', async () => {
    const fetch = vi.fn(async (_url: string) => jsonResponse({ ...makeLogCommit(), files: [], files_truncated: false }))
    vi.stubGlobal('fetch', fetch)
    const store = useGitLogStore()
    for (let i = 0; i < 128; i++) await store.commit(1, REPO, String(i))
    await store.commit(1, REPO, '0')
    await store.commit(1, REPO, '128')
    await store.commit(1, REPO, '0')
    expect(fetch).toHaveBeenCalledTimes(129)
    await store.commit(1, REPO, '1')
    expect(fetch).toHaveBeenCalledTimes(130)
  })

  it('remove cache e histórico ao excluir projeto sem afetar outro', async () => {
    const fetch = vi.fn(async (_url: string, init?: RequestInit) => init?.method === 'DELETE'
      ? new Response(null, { status: 204 })
      : jsonResponse(page(0, 1)))
    vi.stubGlobal('fetch', fetch)
    const store = useGitLogStore()
    await store.load(1, REPO)
    await store.load(2, REPO)
    await useProjectsStore().remove(1)
    expect(store.logFor(1, REPO)).toBeNull()
    expect(store.logFor(2, REPO)?.commits).toHaveLength(1)
  })

  it('não mantém diffs acima do orçamento nem reutiliza cache de projeto removido', async () => {
    const fetch = vi.fn(async () => jsonResponse({ diff: 'x'.repeat(3 * 1024 * 1024), truncated: false }))
    vi.stubGlobal('fetch', fetch)
    const store = useGitLogStore()
    await store.commitDiff(1, REPO, HEAD, 'large')
    await store.commitDiff(1, REPO, HEAD, 'large')
    expect(fetch).toHaveBeenCalledTimes(2)
    fetch.mockImplementation(async () => jsonResponse({ diff: '+small', truncated: false }))
    await store.commitDiff(1, REPO, HEAD, 'small')
    store.forgetProject(1)
    await store.commitDiff(1, REPO, HEAD, 'small')
    expect(fetch).toHaveBeenCalledTimes(4)
  })

  it('não ressuscita páginas pendentes depois de excluir projeto', async () => {
    let release!: (response: Response) => void
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>((resolve) => { release = resolve })))
    const store = useGitLogStore()
    const pending = store.load(1, REPO)
    store.forgetProject(1)
    release(jsonResponse(page(0, 1)))
    await pending
    expect(store.logFor(1, REPO)).toBeNull()
  })
})
