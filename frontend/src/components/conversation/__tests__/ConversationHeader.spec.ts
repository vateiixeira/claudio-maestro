import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import ConversationHeader from '../ConversationHeader.vue'
import { useGitStore } from '../../../stores/git'
import { useGroupsStore } from '../../../stores/groups'
import { useProjectsStore } from '../../../stores/projects'
import { useSessionsStore } from '../../../stores/sessions'
import { makeGroup, makeProject, makeSession } from '../../../test/factories'

enableAutoUnmount(afterEach)
let pinia: Pinia

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  const projects = useProjectsStore(pinia)
  projects.projects = [makeProject({ id: 1 })]
  projects.loaded = true
  useGitStore(pinia).set(1, [])
  useGroupsStore(pinia).groups = [makeGroup({ id: 2, name: 'Checkout' })]
})
afterEach(() => vi.unstubAllGlobals())

function mountHeader(groupId: number | null) {
  useSessionsStore(pinia).setForProject(1, [makeSession({ session_id: 's1', group_id: groupId })])
  return mount(ConversationHeader, { props: { id: 's1' }, global: { plugins: [pinia] } })
}

describe('chip do agrupador no cabeçalho', () => {
  it('mostra o nome do agrupador da sessão', () => {
    expect(mountHeader(2).find('[data-test="header-group"]').text()).toContain('Checkout')
  })

  it('esconde o glifo decorativo dos leitores de tela', () => {
    const chip = mountHeader(2).find('[data-test="header-group"]')
    const glyph = chip.find('[aria-hidden="true"]')
    expect(glyph.exists()).toBe(true)
    expect(glyph.text()).toBe('▤')
    expect(chip.text()).toContain('Checkout')
  })

  it('não mostra nada sem agrupador ou com agrupador desconhecido', () => {
    expect(mountHeader(null).find('[data-test="header-group"]').exists()).toBe(false)
    expect(mountHeader(99).find('[data-test="header-group"]').exists()).toBe(false)
  })
})

describe('ícone de estado no cabeçalho', () => {
  it('é discreto numa espera comum e laranja quando precisa de você', () => {
    useSessionsStore(pinia).setForProject(1, [makeSession({ session_id: 's1', display_state: 'waiting', unread: false })])
    const calm = mount(ConversationHeader, { props: { id: 's1' }, global: { plugins: [pinia] } })
    expect(calm.find('[data-shape]').attributes('data-shape')).toBe('triangle-quiet')

    useSessionsStore(pinia).setForProject(1, [makeSession({ session_id: 's1', display_state: 'waiting', unread: true })])
    const loud = mount(ConversationHeader, { props: { id: 's1' }, global: { plugins: [pinia] } })
    expect(loud.find('[data-shape]').attributes('data-shape')).toBe('triangle')
  })
})
