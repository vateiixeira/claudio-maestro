import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { useGitDetailsStore } from '../gitDetails'
import { useGitStore } from '../git'
import { jsonResponse, makeGitRepo, makeRepoDetails, routeFetch } from '../../test/factories'

const URL = 'GET /api/projects/1/git/details'

function gitEvent(projectId: number) {
  return { session_id: null, seq: 0, type: 'project.git', data: { project_id: projectId, repos: [makeGitRepo()] } } as never
}

beforeEach(() => {
  vi.useFakeTimers()
  setActivePinia(createPinia())
})
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('store de detalhes do git', () => {
  it('carrega e guarda os detalhes do projeto', async () => {
    vi.stubGlobal('fetch', routeFetch({
      [URL]: () => jsonResponse({ repos: [makeRepoDetails({ branch: 'dev' })], limit_reached: true }),
    }))
    const details = useGitDetailsStore()
    expect(details.isLoaded(1)).toBe(false)
    await details.load(1)
    expect(details.isLoaded(1)).toBe(true)
    expect(details.reposFor(1).map((r) => r.branch)).toEqual(['dev'])
    expect(details.errorFor(1)).toBeNull()
  })

  it('guarda a mensagem de erro e limpa na próxima carga bem-sucedida', async () => {
    let fail = true
    vi.stubGlobal('fetch', routeFetch({
      [URL]: () => (fail ? jsonResponse({ detail: 'O git falhou.' }, 500) : jsonResponse({ repos: [], limit_reached: false })),
    }))
    const details = useGitDetailsStore()
    await details.load(1)
    expect(details.errorFor(1)).toBe('O git falhou.')
    expect(details.isLoaded(1)).toBe(false)
    fail = false
    await details.load(1)
    expect(details.errorFor(1)).toBeNull()
    expect(details.isLoaded(1)).toBe(true)
  })

  it('ignora a resposta antiga que chega depois de uma nova', async () => {
    const resolvers: Array<(r: Response) => void> = []
    vi.stubGlobal('fetch', routeFetch({
      [URL]: () => new Promise<Response>((resolve) => resolvers.push(resolve)),
    }))
    const details = useGitDetailsStore()
    const first = details.load(1)
    const second = details.load(1)
    resolvers[1]!(jsonResponse({ repos: [makeRepoDetails({ branch: 'nova' })], limit_reached: false }))
    await second
    resolvers[0]!(jsonResponse({ repos: [makeRepoDetails({ branch: 'velha' })], limit_reached: false }))
    await first
    expect(details.reposFor(1).map((r) => r.branch)).toEqual(['nova'])
  })

  it('erro de uma carga antiga não apaga os dados da nova', async () => {
    const resolvers: Array<(r: Response) => void> = []
    vi.stubGlobal('fetch', routeFetch({
      [URL]: () => new Promise<Response>((resolve) => resolvers.push(resolve)),
    }))
    const details = useGitDetailsStore()
    const first = details.load(1)
    const second = details.load(1)
    resolvers[1]!(jsonResponse({ repos: [makeRepoDetails({ branch: 'nova' })], limit_reached: false }))
    await second
    resolvers[0]!(jsonResponse({ detail: 'falhou' }, 500))
    await first
    expect(details.errorFor(1)).toBeNull()
    expect(details.reposFor(1)).toHaveLength(1)
  })

  it('project.git de um projeto aberto recarrega uma vez, com debounce de 500 ms', async () => {
    const fetchMock = routeFetch({ [URL]: () => jsonResponse({ repos: [], limit_reached: false }) })
    vi.stubGlobal('fetch', fetchMock)
    const details = useGitDetailsStore()
    const git = useGitStore()
    details.open(1)
    await flushPromises()
    expect(fetchMock).toHaveBeenCalledTimes(1)

    git.applyEvent(gitEvent(1))
    await vi.advanceTimersByTimeAsync(300)
    git.applyEvent(gitEvent(1))
    await vi.advanceTimersByTimeAsync(300)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(250)
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('não recarrega projetos que não estão abertos', async () => {
    const fetchMock = routeFetch({
      [URL]: () => jsonResponse({ repos: [], limit_reached: false }),
      'GET /api/projects/2/git/details': () => jsonResponse({ repos: [], limit_reached: false }),
    })
    vi.stubGlobal('fetch', fetchMock)
    const details = useGitDetailsStore()
    const git = useGitStore()
    git.applyEvent(gitEvent(1))
    details.open(2)
    await flushPromises()
    details.close(2)
    fetchMock.mockClear()
    git.applyEvent(gitEvent(2))
    await vi.advanceTimersByTimeAsync(1000)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('fechar cancela a recarga pendente', async () => {
    const fetchMock = routeFetch({ [URL]: () => jsonResponse({ repos: [], limit_reached: false }) })
    vi.stubGlobal('fetch', fetchMock)
    const details = useGitDetailsStore()
    details.open(1)
    await flushPromises()
    useGitStore().applyEvent(gitEvent(1))
    details.close(1)
    await vi.advanceTimersByTimeAsync(1000)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('com dois usos abertos no mesmo projeto, só o último a fechar desliga a recarga', async () => {
    const fetchMock = routeFetch({ [URL]: () => jsonResponse({ repos: [], limit_reached: false }) })
    vi.stubGlobal('fetch', fetchMock)
    const details = useGitDetailsStore()
    details.open(1)
    details.open(1)
    details.close(1)
    await flushPromises()
    fetchMock.mockClear()
    useGitStore().applyEvent(gitEvent(1))
    await vi.advanceTimersByTimeAsync(600)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('reloadOpen recarrega só os projetos abertos', async () => {
    const fetchMock = routeFetch({
      [URL]: () => jsonResponse({ repos: [], limit_reached: false }),
      'GET /api/projects/2/git/details': () => jsonResponse({ repos: [], limit_reached: false }),
    })
    vi.stubGlobal('fetch', fetchMock)
    const details = useGitDetailsStore()
    details.open(1)
    await flushPromises()
    fetchMock.mockClear()
    details.reloadOpen()
    await flushPromises()
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock.mock.calls[0]![0]).toBe('/api/projects/1/git/details')
  })

  it('o contador de recarga sobe a cada carga bem-sucedida, e só nela', async () => {
    let fail = false
    vi.stubGlobal('fetch', routeFetch({
      [URL]: () => (fail ? jsonResponse({ detail: 'x' }, 500) : jsonResponse({ repos: [], limit_reached: false })),
    }))
    const details = useGitDetailsStore()
    expect(details.revisionFor(1)).toBe(0)
    await details.load(1)
    expect(details.revisionFor(1)).toBe(1)
    await details.load(1)
    expect(details.revisionFor(1)).toBe(2)
    fail = true
    await details.load(1)
    expect(details.revisionFor(1)).toBe(2)
  })

  describe('cancelamento', () => {
    /** Fetch that stays pending until aborted, recording each request's signal. */
    function pendingFetch() {
      const signals: AbortSignal[] = []
      const fetchMock = routeFetch({
        [URL]: (init) => new Promise<Response>((_resolve, reject) => {
          const signal = init?.signal as AbortSignal
          signals.push(signal)
          signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
        }),
      })
      vi.stubGlobal('fetch', fetchMock)
      return { signals, fetchMock }
    }

    it('uma nova carga do mesmo projeto aborta a requisição anterior', async () => {
      const { signals } = pendingFetch()
      const details = useGitDetailsStore()
      const first = details.load(1)
      await flushPromises()
      expect(signals[0]!.aborted).toBe(false)
      const second = details.load(1)
      await flushPromises()
      expect(signals[0]!.aborted).toBe(true)
      expect(signals[1]!.aborted).toBe(false)
      // O aborto não vira erro visível nem derruba o estado de carregando da nova.
      await first
      expect(details.errorFor(1)).toBeNull()
      expect(details.isLoading(1)).toBe(true)
      details.close(1)
      await second
    })

    it('close aborta a requisição em andamento sem mostrar erro', async () => {
      const { signals } = pendingFetch()
      const details = useGitDetailsStore()
      details.open(1)
      await flushPromises()
      expect(signals[0]!.aborted).toBe(false)
      details.close(1)
      await flushPromises()
      expect(signals[0]!.aborted).toBe(true)
      expect(details.errorFor(1)).toBeNull()
      expect(details.isLoading(1)).toBe(false)
    })

    it('close de um uso quando ainda há outro aberto não aborta', async () => {
      const { signals } = pendingFetch()
      const details = useGitDetailsStore()
      details.open(1)
      details.open(1)
      await flushPromises()
      details.close(1)
      expect(signals.at(-1)!.aborted).toBe(false)
    })

    it('projetos diferentes não se abortam', async () => {
      const signals: Record<string, AbortSignal> = {}
      vi.stubGlobal('fetch', routeFetch({
        [URL]: (init) => { signals['1'] = init?.signal as AbortSignal; return new Promise<Response>(() => {}) },
        'GET /api/projects/2/git/details': (init) => { signals['2'] = init?.signal as AbortSignal; return new Promise<Response>(() => {}) },
      }))
      const details = useGitDetailsStore()
      void details.load(1)
      void details.load(2)
      await flushPromises()
      expect(signals['1']!.aborted).toBe(false)
      expect(signals['2']!.aborted).toBe(false)
    })
  })
})
