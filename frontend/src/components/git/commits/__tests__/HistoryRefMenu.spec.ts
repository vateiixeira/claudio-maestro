import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import HistoryRefMenu from '../HistoryRefMenu.vue'
import { jsonResponse, makeBranchList, routeFetch } from '../../../../test/factories'

enableAutoUnmount(afterEach)
beforeEach(() => setActivePinia(createPinia()))
afterEach(() => vi.unstubAllGlobals())

describe('menu da branch do histórico', () => {
  it('lista locais e remotas, filtra e escolhe sem trocar de branch', async () => {
    const fetchMock = routeFetch({ [`GET /api/projects/1/git/branches?${new URLSearchParams({ repo: '/r' })}`]: () => jsonResponse(makeBranchList()) })
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = mount(HistoryRefMenu, { props: { projectId: 1, repoPath: '/r', current: 'refs/heads/main' } })
    await flushPromises()
    expect(wrapper.findAll('[role="option"]').map((o) => o.text())).toEqual(['main', 'feat/relatorios', 'origin/main'])
    await wrapper.find('input').setValue('rel')
    expect(wrapper.findAll('[role="option"]').map((o) => o.text())).toEqual(['feat/relatorios'])
    await wrapper.find('[role="option"]').trigger('click')
    expect(wrapper.emitted('select')).toEqual([['refs/heads/feat/relatorios']])
    expect(fetchMock.mock.calls.every(([, init]) => (init?.method ?? 'GET') === 'GET')).toBe(true)
  })

  it('Esc fecha', async () => {
    vi.stubGlobal('fetch', routeFetch({ [`GET /api/projects/1/git/branches?${new URLSearchParams({ repo: '/r' })}`]: () => jsonResponse(makeBranchList()) }))
    const wrapper = mount(HistoryRefMenu, { props: { projectId: 1, repoPath: '/r', current: null } })
    await flushPromises()
    await wrapper.find('input').trigger('keydown', { key: 'Escape' })
    expect(wrapper.emitted('close')).toHaveLength(1)
  })
})
