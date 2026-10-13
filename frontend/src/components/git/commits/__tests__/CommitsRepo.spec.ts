import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import CommitsRepo from '../CommitsRepo.vue'
import { jsonResponse, logUrl, makeLogCommit, makeRepoDetails, makeRepoLog, routeFetch } from '../../../../test/factories'

enableAutoUnmount(afterEach)

const API = '/home/vi/dev/loja/api'
let pinia: Pinia

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
})
afterEach(() => vi.unstubAllGlobals())

describe('repositório da seção Commits', () => {
  it('reabrir um repositório já carregado relê o histórico', async () => {
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
    expect(served).toBe(1)
    expect(wrapper.text()).toContain('novo')
    expect(wrapper.text()).not.toContain('antigo')
  })
})
