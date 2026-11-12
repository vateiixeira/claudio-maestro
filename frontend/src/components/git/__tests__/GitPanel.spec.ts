import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import GitPanel from '../GitPanel.vue'
import { jsonResponse, makeRepoDetails, routeFetch } from '../../../test/factories'

enableAutoUnmount(afterEach)
beforeEach(() => localStorage.clear())
afterEach(() => vi.unstubAllGlobals())

async function setup() {
  const repos = [
    makeRepoDetails({ path: '/p/api', rel_path: 'api', ahead: 2 }),
    makeRepoDetails({ path: '/p/web', rel_path: 'web', ahead: 0, behind: 0 }),
    makeRepoDetails({ path: '/p/error', rel_path: 'broken', error: 'Falhou' }),
  ]
  vi.stubGlobal('fetch', routeFetch({ 'GET /api/projects/1/git/details': () => jsonResponse({ repos, limit_reached: false }) }))
  const wrapper = mount(GitPanel, { props: { projectId: 1 }, global: { plugins: [createPinia()] } })
  await flushPromises()
  return wrapper
}

it('filtra por nome e pendências, mantendo erros visíveis e opção de limpar', async () => {
  const wrapper = await setup()
  expect(wrapper.findAll('[data-test="scm-repo"]')).toHaveLength(3)
  await wrapper.get('[data-test="git-pending-filter"]').trigger('click')
  expect(wrapper.findAll('[data-test="scm-repo"]')).toHaveLength(2)
  await wrapper.get('[data-test="git-repo-search"]').setValue('WEB')
  expect(wrapper.findAll('[data-test="scm-repo"]')).toHaveLength(0)
  expect(wrapper.get('[data-test="git-filter-empty"]').text()).toContain('Nenhum repositório')
  await wrapper.get('[data-test="git-clear-filters"]').trigger('click')
  expect(wrapper.findAll('[data-test="scm-repo"]')).toHaveLength(3)
})

it('abre diretamente o histórico do repositório, sem repetir a lista de alterações', async () => {
  const wrapper = await setup()
  await wrapper.get('[data-repo="/p/api"] [data-test="repo-history"]').trigger('click')
  await flushPromises()
  expect(wrapper.get('[data-test="scm-section"]').isVisible()).toBe(false)
  const target = wrapper.get('[data-repo="/p/api"] [data-test="commits-repo-toggle"]')
  expect(target.attributes('aria-expanded')).toBe('true')
  await wrapper.get('[data-test="git-view-changes"]').trigger('click')
  expect(wrapper.findAll('[data-test="scm-repo"]')).toHaveLength(3)
})

it('reabre o histórico pelo atalho mesmo depois de recolher esse repositório', async () => {
  const wrapper = await setup()
  await wrapper.get('[data-repo="/p/api"] [data-test="repo-history"]').trigger('click')
  await flushPromises()
  await wrapper.get('[data-repo="/p/api"] [data-test="commits-repo-toggle"]').trigger('click')
  await wrapper.get('[data-test="git-view-changes"]').trigger('click')
  await wrapper.get('[data-repo="/p/api"] [data-test="repo-history"]').trigger('click')
  expect(wrapper.get('[data-repo="/p/api"] [data-test="commits-repo-toggle"]').attributes('aria-expanded')).toBe('true')
})
