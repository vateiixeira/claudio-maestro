import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import BranchMenu from '../BranchMenu.vue'
import { jsonResponse, makeRepoDetails, routeFetch } from '../../../../test/factories'
import type { BranchList } from '../../../../types/api'

enableAutoUnmount(afterEach)
const PATH = '/p/api'
const LIST: BranchList = {
  current: 'refs/heads/develop',
  local: [
    { name: 'develop', ref: 'refs/heads/develop', sha: 'a1', date: '2026-10-13T10:00:00-03:00', upstream: 'origin/develop' },
    { name: 'feat/agente', ref: 'refs/heads/feat/agente', sha: 'b2', date: '2026-10-12T10:00:00-03:00', upstream: null },
  ],
  remote: [
    { name: 'origin/develop', ref: 'refs/remotes/origin/develop', sha: 'a1', date: '2026-10-13T10:00:00-03:00', upstream: null },
    { name: 'origin/hotfix/fuso', ref: 'refs/remotes/origin/hotfix/fuso', sha: 'c3', date: '2026-10-10T10:00:00-03:00', upstream: null },
  ],
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.stubGlobal('fetch', routeFetch({ [`GET /api/projects/1/git/branches?${new URLSearchParams({ repo: PATH })}`]: () => jsonResponse(LIST) }))
})
afterEach(() => vi.unstubAllGlobals())

async function open(mode: 'switch' | 'merge' = 'switch') {
  const wrapper = mount(BranchMenu, { props: { projectId: 1, repo: makeRepoDetails({ path: PATH, branch: 'develop' }), mode, canMerge: true }, attachTo: document.body })
  await flushPromises()
  return wrapper
}

describe('menu de branches', () => {
  it('lista criar, locais e remotas sem a que já tem local, e marca a atual', async () => {
    const wrapper = await open()
    expect(document.activeElement?.getAttribute('data-test')).toBe('branch-search')
    const names = wrapper.findAll('[data-test="branch-item"]').map((i) => i.attributes('data-name'))
    expect(names).toEqual(['develop', 'feat/agente', 'origin/hotfix/fuso'])
    expect(wrapper.find('[data-test="branch-create"]').text()).toBe('Criar branch a partir de develop…')
    expect(wrapper.find('[data-name="develop"]').text()).toContain('atual')
    expect(wrapper.find('[data-name="origin/hotfix/fuso"]').text()).toContain('cria local')
  })

  it('filtra, e o criar usa o texto digitado', async () => {
    const wrapper = await open()
    await wrapper.find('[data-test="branch-search"]').setValue('hot')
    expect(wrapper.findAll('[data-test="branch-item"]').map((i) => i.attributes('data-name'))).toEqual(['origin/hotfix/fuso'])
    expect(wrapper.find('[data-test="branch-create"]').text()).toBe('Criar branch hot')
    await wrapper.find('[data-test="branch-create"]').trigger('click')
    expect(wrapper.emitted('create')).toEqual([['hot']])
  })

  it('setas e Enter trocam; Esc fecha', async () => {
    const wrapper = await open()
    const search = wrapper.find('[data-test="branch-search"]')
    await search.trigger('keydown', { key: 'ArrowDown' })
    await search.trigger('keydown', { key: 'ArrowDown' })
    expect(search.attributes('aria-activedescendant')).toBe(wrapper.find('[data-name="feat/agente"]').attributes('id'))
    await search.trigger('keydown', { key: 'Enter' })
    expect(wrapper.emitted('switch')?.[0][0]).toMatchObject({ ref: 'refs/heads/feat/agente' })
    await search.trigger('keydown', { key: 'Escape' })
    expect(wrapper.emitted('close')).toHaveLength(1)
  })

  it('o ícone de merge mescla; no modo merge a linha mescla e a atual some', async () => {
    const wrapper = await open()
    await wrapper.find('[data-name="feat/agente"] [data-test="branch-merge"]').trigger('click')
    expect(wrapper.emitted('merge')?.[0][0]).toMatchObject({ name: 'feat/agente' })
    expect(wrapper.find('[data-name="develop"] [data-test="branch-merge"]').exists()).toBe(false)
    wrapper.unmount()
    const merging = await open('merge')
    expect(merging.find('[data-test="branch-create"]').exists()).toBe(false)
    expect(merging.find('[data-name="develop"]').exists()).toBe(false)
    await merging.find('[data-name="feat/agente"]').trigger('click')
    expect(merging.emitted('merge')).toHaveLength(1)
  })

  it('enquanto a lista não chegou, Enter não escolhe nada', async () => {
    vi.stubGlobal('fetch', routeFetch({ [`GET /api/projects/1/git/branches?${new URLSearchParams({ repo: PATH })}`]: () => new Promise<Response>(() => {}) }))
    const wrapper = await open()
    await wrapper.find('[data-test="branch-search"]').setValue('main')
    await wrapper.find('[data-test="branch-search"]').trigger('keydown', { key: 'Enter' })
    expect(wrapper.emitted('create')).toBeUndefined()
    expect(wrapper.emitted('switch')).toBeUndefined()
  })

  it('aria-controls só existe quando a lista existe', async () => {
    vi.stubGlobal('fetch', routeFetch({ [`GET /api/projects/1/git/branches?${new URLSearchParams({ repo: PATH })}`]: () => new Promise<Response>(() => {}) }))
    const loading = await open()
    expect(loading.find('[data-test="branch-search"]').attributes('aria-controls')).toBeUndefined()
    loading.unmount()
    vi.stubGlobal('fetch', routeFetch({ [`GET /api/projects/1/git/branches?${new URLSearchParams({ repo: PATH })}`]: () => jsonResponse(LIST) }))
    const loaded = await open()
    const id = loaded.find('[data-test="branch-search"]').attributes('aria-controls')
    expect(id).toBeTruthy()
    expect(document.getElementById(id as string)).not.toBeNull()
  })

  it('Esc fecha com o foco em qualquer lugar do menu, e só uma vez', async () => {
    const wrapper = await open()
    wrapper.find<HTMLElement>('[data-test="branch-merge"]').element.focus()
    document.activeElement?.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }))
    expect(wrapper.emitted('close')).toHaveLength(1)
    document.body.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    const closes = wrapper.emitted('close') as unknown[][]
    expect(closes).toHaveLength(2)
    wrapper.unmount()
    document.body.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    expect(closes).toHaveLength(2)
  })

  it('fecha quando o foco sai do menu, sem devolver o foco; foco interno e clique em texto não fecham', async () => {
    const outside = document.createElement('button')
    document.body.appendChild(outside)
    const wrapper = await open()
    const menu = wrapper.find('[data-test="branch-menu"]')
    await menu.trigger('focusout', { relatedTarget: wrapper.find('[data-test="branch-item"]').element })
    await menu.trigger('focusout', { relatedTarget: null })
    expect(wrapper.emitted('close')).toBeUndefined()
    await menu.trigger('focusout', { relatedTarget: outside })
    expect(wrapper.emitted('close')).toEqual([[false]])
    outside.remove()
  })

  it('clicar fora (no fundo) fecha', async () => {
    const wrapper = await open()
    await wrapper.find('[data-test="branch-menu-backdrop"]').trigger('click')
    expect(wrapper.emitted('close')).toHaveLength(1)
  })
})
