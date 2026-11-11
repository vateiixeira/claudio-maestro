import { ref } from 'vue'
import { useGitDetailsStore } from '../../../../stores/gitDetails'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import CommitsRepo from '../CommitsRepo.vue'
import { useGitLogStore } from '../../../../stores/gitLog'
import { jsonResponse, logUrl, makeLogCommit, makeRepoDetails, makeRepoLog, routeFetch } from '../../../../test/factories'

enableAutoUnmount(afterEach)

const API = '/home/vi/dev/loja/api'
let pinia: Pinia

beforeEach(() => {
  localStorage.clear()
  pinia = createPinia()
  setActivePinia(pinia)
})
afterEach(() => vi.unstubAllGlobals())

describe('repositório da seção Commits', () => {
  it('mantém expansão, mas só consulta histórico enquanto a visualização está ativa', async () => {
    const revision = ref(0)
    vi.spyOn(useGitDetailsStore(), 'historyRevisionFor').mockImplementation(() => revision.value)
    const fetch = vi.fn(async () => jsonResponse(makeRepoLog({ head_sha: 'a'.repeat(40) })))
    vi.stubGlobal('fetch', fetch)
    const wrapper = mount(CommitsRepo, {
      props: { projectId: 1, repo: makeRepoDetails({ path: API }), collapseAll: 0, startOpen: true, active: false },
      global: { plugins: [pinia] },
    })
    await flushPromises()
    expect(fetch).not.toHaveBeenCalled()
    await wrapper.setProps({ active: true })
    await flushPromises()
    expect(fetch).toHaveBeenCalledTimes(1)
    await wrapper.setProps({ active: false })
    revision.value++
    await flushPromises()
    expect(fetch).toHaveBeenCalledTimes(1)
    expect(wrapper.get('[data-test="commits-repo-toggle"]').attributes('aria-expanded')).toBe('true')
    await wrapper.setProps({ active: true })
    await flushPromises()
    expect(fetch).toHaveBeenCalledTimes(2)
  })

  it('compara a branch atual quando o histórico segue HEAD e ainda mostra snapshot antigo', async () => {
    const fetch = vi.fn(async (url: string) => url.includes('/comparison?')
      ? jsonResponse({ head_ref: 'refs/heads/feature', base_ref: 'refs/remotes/origin/main', head_sha: 'b'.repeat(40), base_sha: 'a'.repeat(40), merge_base: 'a'.repeat(40), ahead_count: 1, behind_count: 0, unrelated: false, notice: null })
      : jsonResponse(makeRepoLog({ head_sha: 'a'.repeat(40), branch: 'main', commits: [makeLogCommit({ subject: 'snapshot antigo' })] })))
    vi.stubGlobal('fetch', fetch)
    const wrapper = mount(CommitsRepo, { props: { projectId: 1, repo: makeRepoDetails({ path: API, branch: 'main', upstream: 'origin/main' }), collapseAll: 0 }, global: { plugins: [pinia] } })
    await wrapper.get('[data-test="commits-repo-toggle"]').trigger('click'); await flushPromises()
    await wrapper.setProps({ repo: makeRepoDetails({ path: API, branch: 'feature', upstream: 'origin/main', ahead: 9, behind: 2 }) })
    expect(wrapper.get('[data-test="history-ref"]').text()).toBe('main')
    expect(wrapper.get('[data-test="sync-counts"]').text()).toBe('em dia')
    useGitLogStore().logFor(1, API)!.loading = true
    await flushPromises()
    expect(wrapper.get('[data-test="sync-counts"]').text()).toBe('em dia')
    useGitLogStore().logFor(1, API)!.loading = false
    expect(wrapper.get('[data-test="comparison-toggle"]').text()).toContain('Comparar feature')
    await wrapper.get('[data-test="comparison-toggle"]').trigger('click'); await flushPromises()
    const url = fetch.mock.calls.find(([url]) => url.includes('/comparison?'))![0]
    expect(new URL(url, 'http://localhost').searchParams.has('ref')).toBe(false)
    expect(wrapper.text()).toContain('referências atuais')
  })

  it('mantém os commits visíveis quando a revalidação falha', async () => {
    let failed = false
    vi.stubGlobal('fetch', vi.fn(async () => failed
      ? jsonResponse({ detail: 'Não foi possível consultar o Git.' }, 502)
      : jsonResponse(makeRepoLog({ head_sha: 'a'.repeat(40), commits: [makeLogCommit({ subject: 'preservado' })] }))))
    const wrapper = mount(CommitsRepo, {
      props: { projectId: 1, repo: makeRepoDetails({ path: API }), collapseAll: 0 },
      global: { plugins: [pinia] },
    })
    await wrapper.get('[data-test="commits-repo-toggle"]').trigger('click')
    await flushPromises()
    failed = true
    await useGitLogStore().refresh(1, API)
    expect(wrapper.get('[role="alert"]').text()).toContain('Não foi possível')
    expect(wrapper.get('[data-test="commit-row"]').text()).toContain('preservado')
  })

  it('carrega e pagina cada direção sem depender da página do histórico', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      const query = new URL(url, 'http://localhost').searchParams
      const direction = query.get('direction')
      const skip = Number(query.get('skip'))
      return jsonResponse(makeRepoLog({
        head_sha: 'a'.repeat(40), upstream_sha: 'b'.repeat(40),
        incoming_count: 101, outgoing_count: 1101,
        commits: direction ? Array.from({ length: 30 }, (_, i) => makeLogCommit({ full_hash: `${direction}-${skip + i}`, subject: `${direction} ${skip + i}` })) : [makeLogCommit({ subject: 'histórico principal' })],
        has_more: !!direction, next_skip: direction ? skip + 30 : null,
      }))
    }))
    const wrapper = mount(CommitsRepo, {
      props: { projectId: 1, repo: makeRepoDetails({ path: API }), collapseAll: 0 },
      global: { plugins: [pinia] },
    })
    await wrapper.get('[data-test="commits-repo-toggle"]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-test="group-incoming"] > button').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('[data-test="incoming-list"] [data-test="commit-row"]')).toHaveLength(30)
    await wrapper.get('[data-test="load-more-incoming"]').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('[data-test="incoming-list"] [data-test="commit-row"]')).toHaveLength(60)
    await wrapper.get('[data-test="group-outgoing"] > button').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('[data-test="outgoing-list"] [data-test="commit-row"]')).toHaveLength(30)
    expect(wrapper.get('[data-test="group-outgoing"]').text()).toContain('1101 commits')
    expect(wrapper.text()).toContain('histórico principal')
  })

  it('preserva leitura durante refresh e aplica novo snapshot apenas pelo botão', async () => {
    let changed = false
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(makeRepoLog({
      head_sha: (changed ? 'b' : 'a').repeat(40),
      commits: [makeLogCommit({ subject: changed ? 'novo' : 'antigo' })],
    }))))
    const wrapper = mount(CommitsRepo, {
      props: { projectId: 1, repo: makeRepoDetails({ path: API }), collapseAll: 0 },
      global: { plugins: [pinia] },
    })
    await wrapper.get('[data-test="commits-repo-toggle"]').trigger('click')
    await flushPromises()
    changed = true
    await useGitLogStore().refresh(1, API)
    expect(wrapper.text()).toContain('antigo')
    await wrapper.get('[data-test="apply-history-update"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('novo')
    expect(wrapper.text()).not.toContain('antigo')
  })

  it('revalida cache após desmontar e mudar a revisão', async () => {
    const revision = ref(0)
    vi.spyOn(useGitDetailsStore(), 'historyRevisionFor').mockImplementation(() => revision.value)
    const fetch = vi.fn(async () => jsonResponse(makeRepoLog({ head_sha: 'a'.repeat(40) })))
    vi.stubGlobal('fetch', fetch)
    const options = { props: { projectId: 1, repo: makeRepoDetails({ path: API }), collapseAll: 0, startOpen: true }, global: { plugins: [pinia] } }
    const first = mount(CommitsRepo, options)
    await flushPromises()
    first.unmount()
    revision.value++
    const next = mount(CommitsRepo, options)
    await flushPromises()
    expect(next.get('[data-test="commits-repo-toggle"]').attributes('aria-expanded')).toBe('true')
    expect(fetch).toHaveBeenCalledTimes(2)
  })

  it('oferece nova tentativa depois de erro inicial', async () => {
    const fetch = vi.fn().mockRejectedValueOnce(new Error('falha')).mockResolvedValue(jsonResponse(makeRepoLog({ commits: [makeLogCommit({ subject: 'recuperado' })] })))
    vi.stubGlobal('fetch', fetch)
    const wrapper = mount(CommitsRepo, { props: { projectId: 1, repo: makeRepoDetails({ path: API }), collapseAll: 0, startOpen: true }, global: { plugins: [pinia] } })
    await flushPromises()
    await wrapper.get('[data-test="history-retry"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('recuperado')
  })

  it('reabrir um repositório já carregado reutiliza o histórico', async () => {
    const revision = ref(0)
    vi.spyOn(useGitDetailsStore(), 'historyRevisionFor').mockImplementation(() => revision.value)
    let served = 0
    const fetchMock = routeFetch({
      [logUrl(1, API)]: () => jsonResponse(makeRepoLog({ commits: [makeLogCommit({ subject: 'antigo' })] })),
      [logUrl(1, API, 0, null, 30)]: () => {
        served += 1
        return jsonResponse(makeRepoLog({ commits: [makeLogCommit({ subject: 'novo' })] }))
      },
    })
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = mount(CommitsRepo, {
      props: { projectId: 1, repo: makeRepoDetails({ path: API, rel_path: 'api' }), collapseAll: 0 },
      global: { plugins: [pinia] },
    })
    const toggle = () => wrapper.find('[data-test="commits-repo-toggle"]').trigger('click')

    await toggle()
    await flushPromises()
    expect(wrapper.text()).toContain('antigo')
    expect(served).toBe(0)

    await toggle()
    expect(wrapper.find('[data-test="commit-row"]').exists()).toBe(false)
    await toggle()
    await flushPromises()
    expect(served).toBe(0)
    expect(wrapper.text()).toContain('antigo')
    expect(wrapper.text()).not.toContain('novo')
    await toggle()
    revision.value++
    await flushPromises()
    expect(served).toBe(0)
    await toggle()
    await flushPromises()
    expect(served).toBe(1)
    expect(wrapper.text()).toContain('novo')
  })
})
