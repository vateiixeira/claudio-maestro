import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { enableAutoUnmount, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import ProjectTag from '../ProjectTag.vue'
import { useProjectsStore } from '../../../stores/projects'
import { makeProject } from '../../../test/factories'

enableAutoUnmount(afterEach)
let pinia: Pinia

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  const projects = useProjectsStore(pinia)
  projects.projects = [makeProject({ id: 1, name: 'loja-online', color: '#B28CFF' })]
  projects.loaded = true
})

describe('ProjectTag', () => {
  it('mostra o nome e o quadradinho na cor do projeto', () => {
    const wrapper = mount(ProjectTag, { props: { projectId: 1 }, global: { plugins: [pinia] } })
    const root = wrapper.get('[data-test="project-tag"]')
    expect(root.text()).toContain('loja-online')
    const swatch = root.find('[style*="background-color"]')
    expect(swatch.exists()).toBe(true)
    expect((swatch.element as HTMLElement).style.backgroundColor).toBe('rgb(178, 140, 255)')
    expect(wrapper.find('[data-test="project-tag-branch"]').exists()).toBe(false)
  })

  it('mostra o ramo em mono quando vem', () => {
    const wrapper = mount(ProjectTag, { props: { projectId: 1, branch: 'main' }, global: { plugins: [pinia] } })
    const branch = wrapper.get('[data-test="project-tag-branch"]')
    expect(branch.text()).toBe('main')
    expect(branch.classes()).toContain('font-mono')
  })

  it('projeto desconhecido não renderiza nada', () => {
    const wrapper = mount(ProjectTag, { props: { projectId: 99 }, global: { plugins: [pinia] } })
    expect(wrapper.find('[data-test="project-tag"]').exists()).toBe(false)
    const none = mount(ProjectTag, { props: { projectId: null }, global: { plugins: [pinia] } })
    expect(none.find('[data-test="project-tag"]').exists()).toBe(false)
  })
})
