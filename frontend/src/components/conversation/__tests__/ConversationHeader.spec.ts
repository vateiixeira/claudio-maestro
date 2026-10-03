import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import ConversationHeader from '../ConversationHeader.vue'
import IconGroup from '../../icons/IconGroup.vue'
import { createAppRouter } from '../../../router'
import { useGitStore } from '../../../stores/git'
import { useGroupsStore } from '../../../stores/groups'
import { useProjectsStore } from '../../../stores/projects'
import { useSessionsStore } from '../../../stores/sessions'
import { makeGitRepo, makeGroup, makeProject, makeSession } from '../../../test/factories'

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

const router = createAppRouter(createMemoryHistory())

function mountHeader(groupId: number | null, props: Record<string, unknown> = {}) {
  useSessionsStore(pinia).setForProject(1, [makeSession({ session_id: 's1', group_id: groupId })])
  return mount(ConversationHeader, { props: { id: 's1', ...props }, global: { plugins: [pinia, router] } })
}

describe('chip do agrupador no cabeçalho', () => {
  it('mostra o nome do agrupador da sessão', () => {
    expect(mountHeader(2).find('[data-test="header-group"]').text()).toContain('Checkout')
  })

  it('usa um ícone SVG escondido dos leitores de tela, não um caractere', () => {
    const chip = mountHeader(2).find('[data-test="header-group"]')
    const icon = chip.find('svg[aria-hidden="true"]')
    expect(icon.exists()).toBe(true)
    expect(chip.text()).toBe('Checkout')
  })

  it('reaproveita o ícone IconGroup da barra lateral', () => {
    const chip = mountHeader(2).find('[data-test="header-group"]')
    const reference = mount(IconGroup).find('svg path').attributes('d')
    expect(chip.find('svg path').attributes('d')).toBe(reference)
    expect(chip.find('svg polygon').exists()).toBe(false)
  })

  it('não mostra nada sem agrupador ou com agrupador desconhecido', () => {
    expect(mountHeader(null).find('[data-test="header-group"]').exists()).toBe(false)
    expect(mountHeader(99).find('[data-test="header-group"]').exists()).toBe(false)
  })
})

describe('ícone de estado no cabeçalho', () => {
  it('é discreto numa espera comum e laranja quando precisa de você', () => {
    useSessionsStore(pinia).setForProject(1, [makeSession({ session_id: 's1', display_state: 'waiting', unread: false })])
    const calm = mount(ConversationHeader, { props: { id: 's1' }, global: { plugins: [pinia, router] } })
    expect(calm.find('[data-shape]').attributes('data-shape')).toBe('triangle-quiet')

    useSessionsStore(pinia).setForProject(1, [makeSession({ session_id: 's1', display_state: 'waiting', unread: true })])
    const loud = mount(ConversationHeader, { props: { id: 's1' }, global: { plugins: [pinia, router] } })
    expect(loud.find('[data-shape]').attributes('data-shape')).toBe('triangle')
  })
})

describe('faixa compacta', () => {
  it('junta caminho curto e título numa só faixa', () => {
    const wrapper = mountHeader(null)
    const strip = wrapper.get('[data-test="header-strip"]')
    expect(strip.get('[data-test="breadcrumb"]').text()).toContain('Conversas')
    expect(strip.get('[data-test="breadcrumb"]').text()).toContain('loja-online')
    expect(strip.find('[data-test="conversation-title"]').exists()).toBe(true)
    expect(strip.get('[data-test="toggle-finished"]').text()).toBe('Finalizar')
    expect(strip.find('[data-test="header-menu"]').exists()).toBe(true)
  })

  it('os links da trilha têm alvo de pelo menos 32px de altura', () => {
    const links = mountHeader(null).get('[data-test="breadcrumb"]').findAll('a')
    expect(links).toHaveLength(2)
    for (const link of links) {
      expect(link.classes()).toEqual(expect.arrayContaining(['inline-flex', 'min-h-8', 'items-center']))
    }
  })

  it('sem o caminho (embutida) mostra só o título', () => {
    const wrapper = mountHeader(null, { showPath: false })
    expect(wrapper.find('[data-test="breadcrumb"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="conversation-title"]').exists()).toBe(true)
  })

  it('o menu e o separador do caminho são SVG, não caracteres', () => {
    const wrapper = mountHeader(null)
    const menu = wrapper.get('[data-test="header-menu"]')
    expect(menu.find('svg[aria-hidden="true"]').exists()).toBe(true)
    expect(menu.text()).toBe('')
    expect(menu.attributes('aria-label')).toBe('Mais ações')
    expect(wrapper.get('[data-test="breadcrumb"]').text()).not.toContain('›')
    expect(wrapper.text()).not.toMatch(/[⋯›▤]/)
  })

  it('o botão "Próxima" fica entre as ações quando outra conversa aguarda você', () => {
    useSessionsStore(pinia).setForProject(1, [
      makeSession({ session_id: 's1' }),
      makeSession({ session_id: 's2', display_state: 'waiting', unread: true }),
    ])
    const wrapper = mount(ConversationHeader, { props: { id: 's1' }, global: { plugins: [pinia, router] } })
    expect(wrapper.get('[data-test="header-strip"] [data-test="next-needs-you"]').text()).toContain('Próxima (1)')
    const embedded = mount(ConversationHeader, { props: { id: 's1', showPath: false }, global: { plugins: [pinia, router] } })
    expect(embedded.find('[data-test="next-needs-you"]').exists()).toBe(false)
  })
})

describe('linha de projeto, agrupador, branch e worktree', () => {
  const repo = makeGitRepo({ branch: 'main' })

  function mountWithGit(props: Record<string, unknown>) {
    useGitStore(pinia).set(1, [repo])
    return mountHeader(2, props)
  }

  it('aparece com o painel Detalhes fechado', () => {
    const wrapper = mountWithGit({ detailsOpen: false })
    const meta = wrapper.get('[data-test="header-meta"]')
    expect(meta.get('[data-test="header-group"]').text()).toContain('Checkout')
    expect(meta.text()).toContain('main')
  })

  it('some com o painel Detalhes aberto, que já mostra isso', () => {
    const wrapper = mountWithGit({ detailsOpen: true })
    expect(wrapper.find('[data-test="header-meta"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="header-group"]').exists()).toBe(false)
  })

  it('com a trilha escondida (largura estreita) o projeto aparece na linha de metadados', () => {
    const wrapper = mountWithGit({ detailsOpen: false })
    const project = wrapper.get('[data-test="header-meta"] [data-test="header-project"]')
    expect(project.text()).toContain('loja-online')
    // Visible only where the breadcrumb is hidden (max-sm).
    expect(project.classes()).toContain('sm:hidden')
  })

  it('só com o projeto, a linha existe apenas onde a trilha está escondida', () => {
    useGitStore(pinia).set(1, [])
    const wrapper = mountHeader(null)
    const meta = wrapper.get('[data-test="header-meta"]')
    expect(meta.classes()).toContain('sm:hidden')
    useGitStore(pinia).set(1, [repo])
    expect(mountHeader(null).get('[data-test="header-meta"]').classes()).not.toContain('sm:hidden')
  })

  it('no modo embutido mostra também o projeto, que o caminho não mostra', () => {
    const wrapper = mountWithGit({ detailsOpen: false, showPath: false })
    expect(wrapper.get('[data-test="header-meta"]').text()).toContain('loja-online')
  })
})

describe('rótulo de estado', () => {
  it('"Aguardando você" quando pede decisão', () => {
    useSessionsStore(pinia).setForProject(1, [makeSession({ session_id: 's1', state: 'awaiting_decision', display_state: 'waiting' })])
    const wrapper = mount(ConversationHeader, { props: { id: 's1' }, global: { plugins: [pinia, router] } })
    expect(wrapper.get('[data-test="state-live"]').text()).toBe('Aguardando você')
  })
})

describe('marcação no cabeçalho', () => {
  it('botão Marcar abre o menu', async () => {
    const w = mountHeader(null)
    await w.find('[data-test="mark-button"]').trigger('click')
    expect(w.findComponent({ name: 'MarkMenu' }).exists()).toBe(true)
  })
  it('etiqueta mostra a marcação e abre o menu ao clicar', async () => {
    useSessionsStore(pinia).setForProject(1, [makeSession({ session_id: 's1', mark: 'blocked', mark_note: 'esperando CI' })])
    const w = mount(ConversationHeader, { props: { id: 's1' }, global: { plugins: [pinia, router] } })
    const chip = w.find('[data-test="mark-chip"]')
    expect(chip.text()).toBe('Bloqueada: esperando CI')
    await chip.trigger('click')
    expect(w.findComponent({ name: 'MarkMenu' }).exists()).toBe(true)
  })
  it('sem marcação não há etiqueta', () => {
    expect(mountHeader(null).find('[data-test="mark-chip"]').exists()).toBe(false)
  })
  it('prioridade aparece como imagem com rótulo, em cinza', () => {
    useSessionsStore(pinia).setForProject(1, [makeSession({ session_id: 's1', priority: true })])
    const w = mount(ConversationHeader, { props: { id: 's1' }, global: { plugins: [pinia, router] } })
    const star = w.find('[data-test="header-priority"]')
    expect(star.attributes('role')).toBe('img')
    expect(star.attributes('aria-label')).toBe('Prioridade')
    expect(star.classes()).toContain('text-fg-muted')
  })
  describe('alternar pelo gatilho', () => {
    const popover = () => document.body.querySelector('[data-test="mark-popover"]')
    const press = (target: Element) => target.dispatchEvent(new Event('pointerdown', { bubbles: true, cancelable: true }))
    afterEach(() => { document.body.innerHTML = '' })

    it('clicar em Marcar com o menu aberto fecha e não reabre', async () => {
      useSessionsStore(pinia).setForProject(1, [makeSession({ session_id: 's1' })])
      const w = mount(ConversationHeader, { props: { id: 's1' }, global: { plugins: [pinia, router] }, attachTo: document.body })
      const button = w.find('[data-test="mark-button"]')
      await button.trigger('click')
      expect(popover()).not.toBeNull()
      expect(button.attributes('aria-expanded')).toBe('true')
      press(button.element)
      await button.trigger('click')
      expect(popover()).toBeNull()
      expect(button.attributes('aria-expanded')).toBe('false')
    })
    it('clicar na etiqueta com o menu aberto pelo botão também fecha', async () => {
      useSessionsStore(pinia).setForProject(1, [makeSession({ session_id: 's1', mark: 'review' })])
      const w = mount(ConversationHeader, { props: { id: 's1' }, global: { plugins: [pinia, router] }, attachTo: document.body })
      await w.find('[data-test="mark-button"]').trigger('click')
      const chip = w.find('[data-test="mark-chip"]')
      press(chip.element)
      await chip.trigger('click')
      expect(popover()).toBeNull()
    })
    it('devolve o foco ao botão Marcar ao fechar com Esc', async () => {
      useSessionsStore(pinia).setForProject(1, [makeSession({ session_id: 's1' })])
      const w = mount(ConversationHeader, { props: { id: 's1' }, global: { plugins: [pinia, router] }, attachTo: document.body })
      const button = w.find<HTMLButtonElement>('[data-test="mark-button"]')
      await button.trigger('click')
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }))
      await w.vm.$nextTick()
      expect(popover()).toBeNull()
      expect(document.activeElement).toBe(button.element)
    })
  })
})
