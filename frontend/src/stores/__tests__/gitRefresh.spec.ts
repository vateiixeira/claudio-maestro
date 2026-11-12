import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { useGitDetailsStore } from '../gitDetails'
import { useGitOpsStore } from '../gitOps'
import { useGitStore } from '../git'
import { jsonResponse, makeRepoDetails, routeFetch } from '../../test/factories'

const A = '/a'
const B = '/b'
const URL = 'GET /api/projects/1/git/details'
const ID = '00000000-0000-4000-8000-000000000001'
const repo = (path = A, head = 'a'.repeat(40)) => makeRepoDetails({ path, head_sha: head })

beforeEach(() => { vi.useFakeTimers(); setActivePinia(createPinia()) })
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks() })

function event(paths: string[] | null, mutationId?: string) {
  useGitStore().applyEvent({ session_id: '', seq: 0, type: 'project.git', data: {
    project_id: 1, repos: [repo(), repo(B)], changed_repos: paths,
    mutation_id: mutationId, mutation_repo: mutationId ? A : undefined,
  } })
}

describe('reconciliação de atualizações Git', () => {
  it('duas seções compartilham a carga inicial e reabrir revalida', async () => {
    const fetch = routeFetch({ [URL]: () => jsonResponse({ repos: [repo()], limit_reached: false }) })
    vi.stubGlobal('fetch', fetch)
    const store = useGitDetailsStore()
    store.open(1); store.open(1)
    await flushPromises()
    expect(fetch).toHaveBeenCalledTimes(1)
    store.close(1); store.close(1); store.open(1)
    await flushPromises()
    expect(fetch).toHaveBeenCalledTimes(2)
  })

  it('alteração de arquivos não invalida histórico; HEAD só invalida seu repo', async () => {
    vi.stubGlobal('fetch', routeFetch({ [URL]: () => jsonResponse({ repos: [repo(), repo(B)], limit_reached: false }) }))
    const store = useGitDetailsStore()
    await store.load(1)
    const a = store.historyRevisionFor(1, A)
    const b = store.historyRevisionFor(1, B)
    const filesB = store.revisionFor(1, B)
    store.replaceRepo(1, { ...repo(), files: [{ path: 'a.txt', status: 'staged', kind: 'M', added: 1, removed: 0 }] })
    expect(store.historyRevisionFor(1, A)).toBe(a)
    expect(store.historyRevisionFor(1, B)).toBe(b)
    expect(store.revisionFor(1, B)).toBe(filesB)
    store.replaceRepo(1, repo(A, 'b'.repeat(40)))
    expect(store.historyRevisionFor(1, A)).toBe(a + 1)
    expect(store.historyRevisionFor(1, B)).toBe(b)
  })

  it('assinatura de refs detecta outra branch e desconhecida revalida conservadoramente', async () => {
    let signature: string | null = 'one'
    vi.stubGlobal('fetch', routeFetch({ [URL]: () => jsonResponse({
      repos: [{ ...repo(), refs_signature: signature }], limit_reached: false,
    }) }))
    const store = useGitDetailsStore()
    store.open(1); await flushPromises()
    const history = store.historyRevisionFor(1, A)
    signature = 'two'
    event([A]); await vi.advanceTimersByTimeAsync(600)
    expect(store.historyRevisionFor(1, A)).toBe(history + 1)
    signature = null
    event([A]); await vi.advanceTimersByTimeAsync(600)
    event([A]); await vi.advanceTimersByTimeAsync(600)
    expect(store.historyRevisionFor(1, A)).toBe(history + 3)
  })

  it('evento e resposta da mesma ação não fazem outra consulta, nas duas ordens', async () => {
    const fetch = routeFetch({ [URL]: () => jsonResponse({ repos: [repo(), repo(B)], limit_reached: false }) })
    vi.stubGlobal('fetch', fetch)
    const store = useGitDetailsStore()
    store.open(1); await flushPromises()
    store.beginMutation(1, A, ID)
    event([A], ID)
    await vi.advanceTimersByTimeAsync(1000)
    expect(fetch).toHaveBeenCalledTimes(1)
    store.finishMutation(1, A, ID, repo())
    event([A], ID)
    await vi.advanceTimersByTimeAsync(1000)
    expect(fetch).toHaveBeenCalledTimes(1)
  })

  it('não perde evento externo nem mudança em outro repo no scan da ação', async () => {
    const fetch = routeFetch({ [URL]: () => jsonResponse({ repos: [repo(), repo(B)], limit_reached: false }) })
    vi.stubGlobal('fetch', fetch)
    const store = useGitDetailsStore()
    store.open(1); await flushPromises()
    store.beginMutation(1, A, ID)
    event([A, B], ID)
    await vi.advanceTimersByTimeAsync(600)
    expect(fetch).toHaveBeenCalledTimes(2)
    // An external edit in A may finish loading before the older action HTTP response.
    event([A])
    await vi.advanceTimersByTimeAsync(600)
    expect(fetch).toHaveBeenCalledTimes(3)
    store.finishMutation(1, A, ID, repo())
    await vi.advanceTimersByTimeAsync(600)
    expect(fetch).toHaveBeenCalledTimes(4)
  })

  it('force sem mudanças de contagem atualiza diff, sem reler histórico', async () => {
    const fetch = routeFetch({ [URL]: () => jsonResponse({ repos: [repo(), repo(B)], limit_reached: false }) })
    vi.stubGlobal('fetch', fetch)
    const store = useGitDetailsStore()
    store.open(1); await flushPromises()
    const files = store.revisionFor(1, A)
    const log = store.historyRevisionFor(1, A)
    event(null)
    await vi.advanceTimersByTimeAsync(600)
    expect(store.revisionFor(1, A)).toBe(files + 1)
    expect(store.historyRevisionFor(1, A)).toBe(log)
    await store.load(1)
    expect(store.historyRevisionFor(1, A)).toBe(log + 1)
  })

  it('falha libera pendência e reconcilia sem bloquear os próximos eventos', async () => {
    const fetch = routeFetch({ [URL]: () => jsonResponse({ repos: [repo()], limit_reached: false }) })
    vi.stubGlobal('fetch', fetch)
    const store = useGitDetailsStore()
    store.open(1); await flushPromises()
    store.beginMutation(1, A, ID)
    event([A], ID)
    store.finishMutation(1, A, ID)
    await vi.advanceTimersByTimeAsync(600)
    expect(fetch).toHaveBeenCalledTimes(2)
    // The server may finish after the client saw a network failure.
    event([A], ID); await vi.advanceTimersByTimeAsync(600)
    expect(fetch).toHaveBeenCalledTimes(3)
  })

  it('reconexão durante ação força revalidação e mantém eventos externos', async () => {
    const fetch = routeFetch({ [URL]: () => jsonResponse({ repos: [repo()], limit_reached: false }) })
    vi.stubGlobal('fetch', fetch)
    const store = useGitDetailsStore()
    store.open(1); await flushPromises()
    const history = store.historyRevisionFor(1, A)
    store.beginMutation(1, A, ID)
    store.reloadOpen(); await flushPromises()
    expect(store.historyRevisionFor(1, A)).toBe(history + 1)
    store.finishMutation(1, A, ID, repo())
    await vi.advanceTimersByTimeAsync(600)
    expect(fetch).toHaveBeenCalledTimes(3)
  })

  it('gitOps registra o id antes de enviar e ecoa no corpo', async () => {
    let body: Record<string, unknown> = {}
    const fetch = routeFetch({
      [URL]: () => jsonResponse({ repos: [repo()], limit_reached: false }),
      'POST /api/projects/1/git/stage': init => {
        body = JSON.parse(String(init?.body))
        event([A], String(body.mutation_id))
        return jsonResponse({ repo: repo(), mutation_id: body.mutation_id })
      },
    })
    vi.stubGlobal('fetch', fetch)
    const store = useGitDetailsStore()
    store.open(1); await flushPromises()
    await useGitOpsStore().run(1, A, 'stage', { paths: ['a.txt'] })
    expect(body.mutation_id).toMatch(/^[0-9a-f-]{36}$/)
    await vi.advanceTimersByTimeAsync(1000)
    expect(fetch).toHaveBeenCalledTimes(2)
  })
})
