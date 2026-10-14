import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useGitOpsStore } from '../gitOps'
import { useGitDetailsStore } from '../gitDetails'
import { jsonResponse, makeRepoDetails, routeFetch } from '../../test/factories'

const REPO = '/home/vi/dev/loja'
beforeEach(() => setActivePinia(createPinia()))
afterEach(() => vi.unstubAllGlobals())

describe('gitOps', () => {
  it('troca o repositório pela resposta e limpa o erro', async () => {
    const details = useGitDetailsStore()
    details.byProject[1] = { repos: [makeRepoDetails({ path: REPO })], limit_reached: false }
    const answer = makeRepoDetails({ path: REPO, branch: 'nova' })
    const fetchMock = routeFetch({ 'POST /api/projects/1/git/commit': () => jsonResponse({ repo: answer }) })
    vi.stubGlobal('fetch', fetchMock)
    const ops = useGitOpsStore()
    const result = await ops.run(1, REPO, 'commit', { message: 'Oi' })
    expect(result?.repo.branch).toBe('nova')
    expect(details.reposFor(1)[0].branch).toBe('nova')
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({ repo: REPO, message: 'Oi' })
    expect(ops.busyFor(REPO)).toBeNull()
  })

  it('marca ocupado e recusa uma segunda ação no mesmo repositório', async () => {
    let release!: () => void
    vi.stubGlobal('fetch', routeFetch({
      'POST /api/projects/1/git/push': () => new Promise<Response>((r) => { release = () => r(jsonResponse({ repo: makeRepoDetails({ path: REPO }) })) }),
    }))
    const ops = useGitOpsStore()
    const first = ops.run(1, REPO, 'push')
    expect(ops.busyFor(REPO)).toBe('push')
    expect(await ops.run(1, REPO, 'commit', { message: 'x' })).toBeNull()
    release()
    await first
    expect(ops.busyFor(REPO)).toBeNull()
  })

  it('guarda a mensagem e a saída do erro', async () => {
    vi.stubGlobal('fetch', routeFetch({
      'POST /api/projects/1/git/push': () => jsonResponse({ detail: { code: 'git', message: 'O envio não foi feito.', output: ' ! [rejected]' } }, 409),
    }))
    const ops = useGitOpsStore()
    expect(await ops.run(1, REPO, 'push')).toBeNull()
    expect(ops.errorFor(REPO)).toEqual({ message: 'O envio não foi feito.', output: ' ! [rejected]' })
    ops.dismiss(REPO)
    expect(ops.errorFor(REPO)).toBeNull()
  })

  it('uma ação em andamento num repositório não bloqueia o outro', async () => {
    const OTHER = '/home/vi/dev/outro'
    let release!: () => void
    vi.stubGlobal('fetch', routeFetch({
      'POST /api/projects/1/git/push': () => new Promise<Response>((r) => { release = () => r(jsonResponse({ repo: makeRepoDetails({ path: REPO }) })) }),
      'POST /api/projects/1/git/commit': () => jsonResponse({ repo: makeRepoDetails({ path: OTHER }) }),
    }))
    const ops = useGitOpsStore()
    const first = ops.run(1, REPO, 'push')
    expect(ops.busyFor(OTHER)).toBeNull()
    const second = await ops.run(1, OTHER, 'commit', { message: 'x' })
    expect(second?.repo.path).toBe(OTHER)
    expect(ops.busyFor(REPO)).toBe('push')
    release()
    await first
  })
})
