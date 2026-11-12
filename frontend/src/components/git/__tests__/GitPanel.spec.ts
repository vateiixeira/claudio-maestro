import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import GitPanel from '../GitPanel.vue'
import { jsonResponse, makeRepoDetails, routeFetch } from '../../../test/factories'

enableAutoUnmount(afterEach)
beforeEach(() => localStorage.clear())
afterEach(() => vi.unstubAllGlobals())

async function setup(focusPath?: string | null) {
  const repos = [
    makeRepoDetails({ path: '/p/api', rel_path: 'api', ahead: 2 }),
    makeRepoDetails({ path: '/p/web', rel_path: 'web', ahead: 0, behind: 0 }),
    makeRepoDetails({ path: '/p/error', rel_path: 'broken', error: 'Falhou' }),
  ]
  vi.stubGlobal('fetch', routeFetch({ 'GET /api/projects/1/git/details': () => jsonResponse({ repos, limit_reached: false }) }))
  const wrapper = mount(GitPanel, { props: { projectId: 1, focusPath }, global: { plugins: [createPinia()] } })
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

it('com focusPath mostra só o repositório dessa pasta e oferece Ver todos', async () => {
  const wrapper = await setup('/p/web')
  expect(wrapper.findAll('[data-test="scm-repo"]')).toHaveLength(1)
  expect(wrapper.get('[data-test="scm-repo"]').attributes('data-repo')).toBe('/p/web')
  expect(wrapper.get('[data-test="git-focus"]').text()).toContain('worktree da conversa')
  expect(wrapper.get('[data-test="git-focus-all"]').text()).toBe('Ver todos')
  expect(wrapper.text()).toContain('1 de 1')

  await wrapper.get('[data-test="git-focus-all"]').trigger('click')
  expect(wrapper.findAll('[data-test="scm-repo"]')).toHaveLength(3)
  expect(wrapper.find('[data-test="git-focus"]').exists()).toBe(false)
})

it('com focusPath, os filtros e o histórico valem dentro do foco', async () => {
  const wrapper = await setup('/p/web')
  await wrapper.get('[data-test="git-repo-search"]').setValue('api')
  expect(wrapper.findAll('[data-test="scm-repo"]')).toHaveLength(0)
  expect(wrapper.find('[data-test="git-filter-empty"]').exists()).toBe(true)
  await wrapper.get('[data-test="git-clear-filters"]').trigger('click')
  await wrapper.get('[data-test="git-view-commits"]').trigger('click')
  await flushPromises()
  expect(wrapper.findAll('[data-test="commits-repo-toggle"]')).toHaveLength(1)
})

it('inclui repositórios dentro da pasta do foco e não confunde pastas com prefixo parecido', async () => {
  const repos = [
    makeRepoDetails({ path: '/p/wt', rel_path: 'wt' }),
    makeRepoDetails({ path: '/p/wt/sub', rel_path: 'wt/sub' }),
    makeRepoDetails({ path: '/p/wt-old', rel_path: 'wt-old' }),
  ]
  vi.stubGlobal('fetch', routeFetch({ 'GET /api/projects/1/git/details': () => jsonResponse({ repos, limit_reached: false }) }))
  const wrapper = mount(GitPanel, { props: { projectId: 1, focusPath: '/p/wt/' }, global: { plugins: [createPinia()] } })
  await flushPromises()
  expect(wrapper.findAll('[data-test="scm-repo"]').map((r) => r.attributes('data-repo'))).toEqual(['/p/wt', '/p/wt/sub'])
})

it('se nenhum repositório está no foco, mostra todos sem o aviso', async () => {
  const wrapper = await setup('/outra/pasta')
  expect(wrapper.findAll('[data-test="scm-repo"]')).toHaveLength(3)
  expect(wrapper.find('[data-test="git-focus"]').exists()).toBe(false)
})

it('trocar o focusPath volta a focar mesmo depois de Ver todos', async () => {
  const wrapper = await setup('/p/web')
  await wrapper.get('[data-test="git-focus-all"]').trigger('click')
  await wrapper.setProps({ focusPath: '/p/api' })
  expect(wrapper.findAll('[data-test="scm-repo"]').map((r) => r.attributes('data-repo'))).toEqual(['/p/api'])
})

it('o repositório focado começa aberto mesmo limpo; sem foco, os limpos seguem recolhidos', async () => {
  const focused = await setup('/p/web')
  expect(focused.get('[data-repo="/p/web"] [data-test="scm-repo-toggle"]').attributes('aria-expanded')).toBe('true')
  focused.unmount()

  localStorage.clear()
  const plain = await setup()
  expect(plain.get('[data-repo="/p/web"] [data-test="scm-repo-toggle"]').attributes('aria-expanded')).toBe('false')
})
