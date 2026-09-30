import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useSessionsStore } from '../sessions'
import { deriveDisplay } from '../../sessionState'
import { jsonResponse, makeSession, routeFetch } from '../../test/factories'

beforeEach(() => setActivePinia(createPinia()))
afterEach(() => vi.unstubAllGlobals())

describe('derivação do estado exibido', () => {
  it.each([
    ['connecting', false, 'running', false],
    ['running', true, 'running', false],
    ['awaiting_decision', false, 'waiting', true],
    ['idle', false, 'waiting', false],
    ['error', false, 'waiting', false],
    ['closed', true, 'finished', false],
    ['idle', true, 'finished', false],
  ] as const)('%s (finalizada=%s) vira %s', (state, finished, display, awaiting) => {
    expect(deriveDisplay(state, finished)).toEqual({ display_state: display, awaiting_decision: awaiting })
  })

  it('session.state atualiza display_state e awaiting_decision', () => {
    const store = useSessionsStore()
    store.setForProject(1, [makeSession({ session_id: 'a' })])
    store.applyEvent({ session_id: 'a', seq: 2, type: 'session.state', data: { state: 'awaiting_decision', error: null } })
    expect(store.find('a')).toMatchObject({ display_state: 'waiting', awaiting_decision: true })
    store.applyEvent({ session_id: 'a', seq: 3, type: 'session.state', data: { state: 'running', error: null } })
    expect(store.find('a')).toMatchObject({ display_state: 'running', awaiting_decision: false })
  })

  it('session.state ociosa mantém em execução enquanto o resumo diz que há subagente rodando', () => {
    const store = useSessionsStore()
    store.setForProject(1, [makeSession({ session_id: 'a', state: 'running', display_state: 'running', subagents_running: true })])
    store.applyEvent({ session_id: 'a', seq: 2, type: 'session.state', data: { state: 'idle', error: null } })
    expect(store.find('a')).toMatchObject({ display_state: 'running', awaiting_decision: false })
    store.applyEvent({ session_id: 'a', seq: 3, type: 'session.updated', data: makeSession({ session_id: 'a', seq: 3, state: 'idle', display_state: 'waiting', subagents_running: false }) })
    store.applyEvent({ session_id: 'a', seq: 4, type: 'session.state', data: { state: 'idle', error: null } })
    expect(store.find('a')).toMatchObject({ display_state: 'waiting' })
  })
})

describe('session.updated e dados velhos', () => {
  it('aplica session.updated substituindo a sessão', () => {
    const store = useSessionsStore()
    store.setForProject(1, [makeSession({ session_id: 'a', seq: 1 })])
    const data = makeSession({ session_id: 'a', seq: 5, finished: true, display_state: 'finished', title: 'Novo' })
    store.applyEvent({ session_id: 'a', seq: 5, type: 'session.updated', data })
    expect(store.find('a')).toMatchObject({ finished: true, display_state: 'finished', title: 'Novo', seq: 5 })
  })

  it('session.updated de sessão desconhecida entra no projeto', () => {
    const store = useSessionsStore()
    store.setForProject(1, [])
    store.applyEvent({ session_id: 'n', seq: 1, type: 'session.updated', data: makeSession({ session_id: 'n', seq: 1 }) })
    expect(store.forProject(1).map((s) => s.session_id)).toEqual(['n'])
  })

  it('ignora listagem mais antiga que um evento recebido que o último evento', async () => {
    let release!: (r: Response) => void
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/projects/1/sessions': () => new Promise<Response>((r) => (release = r)),
    }))
    const store = useSessionsStore()
    store.setForProject(1, [makeSession({ session_id: 'a', seq: 1 })])
    const loading = store.loadForProject(1)
    store.applyEvent({ session_id: 'a', seq: 7, type: 'session.updated', data: makeSession({ session_id: 'a', seq: 7, title: 'Do evento' }) })
    release(jsonResponse([makeSession({ session_id: 'a', seq: 3, title: 'Da lista' }), makeSession({ session_id: 'b', seq: 2 })]))
    await loading
    expect(store.find('a')?.title).toBe('Do evento')
    expect(store.find('b')).toBeDefined()
  })

  it('descarta resposta de listagem mais antiga que uma posterior', async () => {
    const releases: Array<(r: Response) => void> = []
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/projects/1/sessions': () => new Promise<Response>((r) => releases.push(r)),
    }))
    const store = useSessionsStore()
    const first = store.loadForProject(1)
    const second = store.loadForProject(1)
    releases[1]!(jsonResponse([makeSession({ session_id: 'a', title: 'Nova' })]))
    await second
    releases[0]!(jsonResponse([makeSession({ session_id: 'a', title: 'Velha' })]))
    await first
    expect(store.find('a')?.title).toBe('Nova')
  })
})

describe('finalizar, reabrir e renomear', () => {
  it('finaliza e reabre via PATCH', async () => {
    const bodies: unknown[] = []
    vi.stubGlobal('fetch', routeFetch({
      'PATCH /api/sessions/a': (init) => {
        const body = JSON.parse(String(init?.body))
        bodies.push(body)
        return jsonResponse(makeSession({ session_id: 'a', seq: bodies.length, finished: body.finished, display_state: body.finished ? 'finished' : 'waiting' }))
      },
    }))
    const store = useSessionsStore()
    store.setForProject(1, [makeSession({ session_id: 'a' })])
    await store.setFinished('a', true)
    expect(store.find('a')?.display_state).toBe('finished')
    await store.setFinished('a', false)
    expect(store.find('a')?.display_state).toBe('waiting')
    expect(bodies).toEqual([{ finished: true }, { finished: false }])
  })

  it('renomeia via PATCH', async () => {
    vi.stubGlobal('fetch', routeFetch({
      'PATCH /api/sessions/a': () => jsonResponse(makeSession({ session_id: 'a', seq: 1, title: 'Outro' })),
    }))
    const store = useSessionsStore()
    store.setForProject(1, [makeSession({ session_id: 'a' })])
    await store.rename('a', 'Outro')
    expect(store.find('a')?.title).toBe('Outro')
  })
})

describe('reinício do backend', () => {
  it('listagem com seq 0 após eventos altos é aplicada e eventos baixos seguem valendo', async () => {
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/projects/1/sessions': () => jsonResponse([makeSession({ session_id: 'a', seq: 0, state: 'idle', display_state: 'waiting' })]),
    }))
    const store = useSessionsStore()
    store.setForProject(1, [makeSession({ session_id: 'a' })])
    store.applyEvent({ session_id: 'a', seq: 7, type: 'session.state', data: { state: 'running', error: null } })
    await store.loadAll([1])
    expect(store.find('a')).toMatchObject({ state: 'idle', display_state: 'waiting' })
    store.applyEvent({ session_id: 'a', seq: 1, type: 'session.state', data: { state: 'running', error: null } })
    expect(store.find('a')?.display_state).toBe('running')
    store.applyEvent({ session_id: 'a', seq: 2, type: 'session.updated', data: makeSession({ session_id: 'a', seq: 2, title: 'Depois' }) })
    expect(store.find('a')?.title).toBe('Depois')
  })

  it('finalizada por inatividade continua finalizada ao receber idle', () => {
    const store = useSessionsStore()
    store.setForProject(1, [makeSession({ session_id: 'a', finished: false, display_state: 'finished' })])
    store.applyEvent({ session_id: 'a', seq: 1, type: 'session.state', data: { state: 'idle', error: null } })
    expect(store.find('a')?.display_state).toBe('finished')
  })
})
