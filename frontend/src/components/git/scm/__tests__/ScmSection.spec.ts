import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import ScmSection from '../ScmSection.vue'
import { useProjectsStore } from '../../../../stores/projects'
import { jsonResponse, makeProject, makeRepoDetails, routeFetch } from '../../../../test/factories'
import type { RepoDetails } from '../../../../types/api'

enableAutoUnmount(afterEach)
const DETAILS = 'GET /api/projects/1/git/details'
let pinia: Pinia

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  useProjectsStore(pinia).projects = [makeProject({ id: 1, name: 'loja' })]
})
afterEach(() => vi.unstubAllGlobals())

async function mountWith(repos: RepoDetails[]) {
  vi.stubGlobal('fetch', routeFetch({ [DETAILS]: () => jsonResponse({ repos, limit_reached: false }) }))
  const wrapper = mount(ScmSection, { props: { projectId: 1 }, global: { plugins: [pinia] } })
  await flushPromises()
  return wrapper
}

describe('seção Alterações', () => {
  it('carregando e erro com tentar de novo', async () => {
    let fail = true
    vi.stubGlobal('fetch', routeFetch({
      [DETAILS]: () => (fail ? jsonResponse({ detail: 'O git falhou.' }, 500) : jsonResponse({ repos: [makeRepoDetails()], limit_reached: false })),
    }))
    const wrapper = mount(ScmSection, { props: { projectId: 1 }, global: { plugins: [pinia] } })
    await flushPromises()
    expect(wrapper.find('[role="alert"]').text()).toContain('O git falhou.')
    fail = false
    await wrapper.find('[data-test="git-retry"]').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('[data-test="scm-repo"]')).toHaveLength(1)
  })

  it('cabeçalho com a contagem e repositório limpo e em dia recolhido', async () => {
    const wrapper = await mountWith([
      makeRepoDetails({ path: '/p/api', rel_path: 'api', files: [{ path: 'a.ts', status: 'unstaged', kind: 'M', added: 1, removed: 0 }] }),
      makeRepoDetails({ path: '/p/web', rel_path: 'web' }),
    ])
    expect(wrapper.find('[data-test="scm-count"]').text()).toBe('2 repositórios')
    const [api, web] = wrapper.findAll('[data-test="scm-repo"]')
    expect(api.find('[data-test="scm-body"]').exists()).toBe(true)
    expect(web.find('[data-test="scm-body"]').exists()).toBe(false)
    await web.find('[data-test="scm-repo-toggle"]').trigger('click')
    expect(web.find('[data-test="scm-body"]').exists()).toBe(true)
    await wrapper.find('[data-test="scm-collapse-all"]').trigger('click')
    expect(wrapper.find('[data-test="scm-body"]').exists()).toBe(false)
  })

  it('erro de um repositório aparece só nele', async () => {
    const wrapper = await mountWith([makeRepoDetails({ path: '/p/x', rel_path: 'x', error: 'Repositório corrompido' })])
    expect(wrapper.find('[data-test="scm-repo-error"]').text()).toBe('Repositório corrompido')
  })
})
