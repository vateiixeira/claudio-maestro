import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import OrgTabs from '../OrgTabs.vue'
import { createAppRouter } from '../../../router'
import { useOrgStore } from '../../../stores/org'
import { makeRoutine } from '../../../test/factories'

enableAutoUnmount(afterEach)
let pinia: Pinia

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  useOrgStore(pinia).loaded = true
})

async function mountTabs(path = '/agentes/1') {
  const router = createAppRouter(createMemoryHistory())
  await router.push(path)
  await router.isReady()
  const wrapper = mount(OrgTabs, { props: { projectId: 1 }, global: { plugins: [pinia, router] }, attachTo: document.body })
  await flushPromises()
  return { wrapper, router }
}

describe('OrgTabs', () => {
  it('a aba Rotinas mostra quantas rotinas o projeto tem', async () => {
    useOrgStore(pinia).routines = { 1: [makeRoutine({ id: 1 }), makeRoutine({ id: 2, name: 'Outra' })] }
    const { wrapper } = await mountTabs()
    expect(wrapper.get('[data-test="org-tab-rotinas"] [data-test="org-tab-count"]').text()).toBe('2')
    expect(wrapper.find('[data-test="org-tab-tarefas"] [data-test="org-tab-count"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="org-tab-execucoes"] [data-test="org-tab-count"]').exists()).toBe(false)
  })

  it('sem rotinas não mostra o número', async () => {
    const { wrapper } = await mountTabs()
    expect(wrapper.find('[data-test="org-tab-count"]').exists()).toBe(false)
  })

  it('o número entra no nome da aba sem trocar o rótulo', async () => {
    useOrgStore(pinia).routines = { 1: [makeRoutine({ id: 1 })] }
    const { wrapper } = await mountTabs()
    expect(wrapper.get('[data-test="org-tab-rotinas"]').text()).toMatch(/^Rotinas\s*1$/)
  })

  it('setas, Home e End trocam de aba e levam o foco', async () => {
    const { wrapper, router } = await mountTabs()
    await wrapper.get('[data-test="org-tab-tarefas"]').trigger('keydown', { key: 'ArrowRight' })
    await flushPromises()
    expect(router.currentRoute.value.query.aba).toBe('rotinas')
    expect(document.activeElement).toBe(wrapper.get('[data-test="org-tab-rotinas"]').element)
    await wrapper.get('[data-test="org-tab-rotinas"]').trigger('keydown', { key: 'End' })
    await flushPromises()
    expect(router.currentRoute.value.query.aba).toBe('execucoes')
    await wrapper.get('[data-test="org-tab-execucoes"]').trigger('keydown', { key: 'ArrowRight' })
    await flushPromises()
    expect(router.currentRoute.value.query.aba).toBe('tarefas')
    await wrapper.get('[data-test="org-tab-tarefas"]').trigger('keydown', { key: 'ArrowLeft' })
    await flushPromises()
    expect(router.currentRoute.value.query.aba).toBe('execucoes')
    await wrapper.get('[data-test="org-tab-execucoes"]').trigger('keydown', { key: 'Home' })
    await flushPromises()
    expect(router.currentRoute.value.query.aba).toBe('tarefas')
  })
})
