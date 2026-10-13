import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import CommitsSection from '../CommitsSection.vue'
import { useProjectsStore } from '../../../../stores/projects'
import { jsonResponse, logUrl, makeLogCommit, makeProject, makeRepoDetails, makeRepoLog, makeRepoState, routeFetch } from '../../../../test/factories'

enableAutoUnmount(afterEach)

const DETAILS = 'GET /api/projects/1/git/details'
const API = '/home/vi/dev/loja/api'
let pinia: Pinia

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  useProjectsStore(pinia).projects = [makeProject({ id: 1, name: 'loja' })]
})
afterEach(() => vi.unstubAllGlobals())

const sha = (n: number) => `${String(n).padStart(7, '0')}${'b'.repeat(33)}`

async function mountWith(log: ReturnType<typeof makeRepoLog>, extra: Record<string, () => Response> = {}) {
  const repo = makeRepoDetails({ path: API, rel_path: 'api', ahead: 2, behind: 1, fetched_at: Date.now() / 1000 - 120, state: makeRepoState({ user_email: 'eu@example.com' }) })
  const fetchMock = routeFetch({
    [DETAILS]: () => jsonResponse({ repos: [repo], limit_reached: false }),
    [logUrl(1, API)]: () => jsonResponse(log),
    ...extra,
  })
  vi.stubGlobal('fetch', fetchMock)
  const wrapper = mount(CommitsSection, { props: { projectId: 1 }, global: { plugins: [pinia] } })
  await flushPromises()
  await wrapper.find('[data-test="commits-repo-toggle"]').trigger('click')
  await flushPromises()
  return { wrapper, fetchMock }
}

describe('seção Commits', () => {
  it('mostra o cabeçalho com a contagem de repositórios e a linha do repositório', async () => {
    const { wrapper } = await mountWith(makeRepoLog())
    expect(wrapper.find('[data-test="commits-title"]').text()).toContain('Commits')
    expect(wrapper.find('[data-test="commits-count"]').text()).toBe('1 repositório')
    const row = wrapper.find('[data-test="commits-repo"]')
    expect(row.text()).toContain('api')
    expect(row.find('[data-test="sync-counts"]').attributes('aria-label')).toBe('1 para baixar, 2 para subir')
    expect(row.find('[data-test="sync-counts"]').text()).toBe('12')
    expect(row.find('[data-test="fetched-ago"]').text()).toBe('buscado há 2 min')
  })

  it('agrupa para subir e para baixar e marca o commit do upstream', async () => {
    const log = makeRepoLog({
      upstream: 'origin/main', upstream_sha: sha(3),
      commits: [
        makeLogCommit({ full_hash: sha(1), subject: 'local 1', pushed: false, email: 'eu@example.com' }),
        makeLogCommit({ full_hash: sha(2), subject: 'local 2', pushed: false }),
        makeLogCommit({ full_hash: sha(3), subject: 'no remoto', pushed: true }),
      ],
      incoming: [makeLogCommit({ full_hash: sha(9), subject: 'do remoto' })],
      incoming_count: 1, outgoing_count: 2,
    })
    const { wrapper } = await mountWith(log)
    expect(wrapper.find('[data-test="group-outgoing"]').text()).toContain('Para subir — 2 commits')
    expect(wrapper.find('[data-test="group-incoming"]').text()).toContain('Para baixar — 1 commit')
    const rows = wrapper.findAll('[data-test="commit-row"]')
    expect(rows).toHaveLength(3)
    expect(rows[0].find('[data-test="commit-unpushed"]').exists()).toBe(true)
    expect(rows[0].text()).toContain('Você')
    expect(rows[2].find('[data-test="upstream-tag"]').text()).toBe('origin')
    await wrapper.find('[data-test="group-incoming"] button').trigger('click')
    expect(wrapper.find('[data-test="incoming-list"]').text()).toContain('do remoto')
  })

  it('marca o upstream entre os commits para baixar quando a branch está atrás', async () => {
    const log = makeRepoLog({
      upstream: 'origin/main', upstream_sha: sha(9),
      commits: [makeLogCommit({ full_hash: sha(1), pushed: true })],
      incoming: [makeLogCommit({ full_hash: sha(9), subject: 'do remoto' })],
      incoming_count: 1, outgoing_count: 0,
    })
    const { wrapper } = await mountWith(log)
    await wrapper.find('[data-test="group-incoming"] button').trigger('click')
    expect(wrapper.find('[data-test="incoming-list"] [data-test="upstream-tag"]').text()).toBe('origin')
  })

  it('"nenhum" quando não há nada para subir ou baixar', async () => {
    const { wrapper } = await mountWith(makeRepoLog({ incoming_count: 0, outgoing_count: 0 }))
    expect(wrapper.find('[data-test="group-outgoing"]').text()).toContain('Para subir — nenhum')
    expect(wrapper.find('[data-test="group-incoming"]').text()).toContain('Para baixar — nenhum')
  })

  it('carrega mais', async () => {
    const first = Array.from({ length: 30 }, (_, i) => makeLogCommit({ full_hash: sha(i), subject: `c${i}` }))
    const { wrapper } = await mountWith(makeRepoLog({ commits: first, has_more: true }), {
      [logUrl(1, API, 30)]: () => jsonResponse(makeRepoLog({ commits: [makeLogCommit({ full_hash: sha(99), subject: 'último' })], has_more: false })),
    })
    await wrapper.find('[data-test="load-more"]').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('[data-test="commit-row"]')).toHaveLength(31)
    expect(wrapper.find('[data-test="load-more"]').exists()).toBe(false)
  })

  it('recolher todos fecha os repositórios abertos', async () => {
    const { wrapper } = await mountWith(makeRepoLog({ commits: [makeLogCommit()] }))
    expect(wrapper.find('[data-test="commit-row"]').exists()).toBe(true)
    await wrapper.find('[data-test="commits-collapse-all"]').trigger('click')
    expect(wrapper.find('[data-test="commit-row"]').exists()).toBe(false)
  })
})
