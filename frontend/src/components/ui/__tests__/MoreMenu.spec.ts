import { afterEach, describe, expect, it } from 'vitest'
import { nextTick } from 'vue'
import { enableAutoUnmount, mount } from '@vue/test-utils'
import MoreMenu from '../MoreMenu.vue'

enableAutoUnmount(afterEach)

const ITEMS = [
  { id: 'edit', label: 'Renomear' },
  { id: 'lock', label: 'Bloqueado', disabled: true },
  { id: 'remove', label: 'Remover', danger: true },
]

function mountMenu(attrs: Record<string, unknown> = {}) {
  const host = document.createElement('div')
  document.body.appendChild(host)
  const wrapper = mount(MoreMenu, { props: { label: 'Mais ações', items: ITEMS }, attrs, attachTo: host })
  return { wrapper, trigger: wrapper.get('button[aria-haspopup="menu"]') }
}
const menuItems = () => Array.from(document.body.querySelectorAll<HTMLElement>('[data-test="more-menu-item"]'))

describe('MoreMenu', () => {
  it('o botão tem nome, aria-haspopup e data-test padrão', () => {
    const { trigger } = mountMenu()
    expect(trigger.attributes('aria-label')).toBe('Mais ações')
    expect(trigger.attributes('data-test')).toBe('more-menu')
    expect(trigger.attributes('aria-expanded')).toBe('false')
  })

  it('o data-test e o id do pai prevalecem no botão', () => {
    const { trigger } = mountMenu({ 'data-test': 'project-actions', id: 'x' })
    expect(trigger.attributes('data-test')).toBe('project-actions')
    expect(trigger.attributes('id')).toBe('x')
  })

  it('Enter abre o menu, teleportado para o body', async () => {
    const { trigger } = mountMenu()
    await trigger.trigger('keydown', { key: 'Enter' })
    await nextTick()
    expect(trigger.attributes('aria-expanded')).toBe('true')
    expect(menuItems().map((i) => i.dataset.id)).toEqual(['edit', 'lock', 'remove'])
  })

  it('seta para baixo foca o primeiro item', async () => {
    const { trigger } = mountMenu()
    await trigger.trigger('keydown', { key: 'ArrowDown' })
    await nextTick()
    await nextTick()
    expect(document.activeElement).toBe(menuItems()[0])
  })

  it('as setas percorrem os itens habilitados', async () => {
    const { trigger } = mountMenu()
    await trigger.trigger('keydown', { key: 'ArrowDown' })
    await nextTick()
    await nextTick()
    const menu = document.body.querySelector('[role="menu"]')!
    menu.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }))
    expect(document.activeElement).toBe(menuItems()[2])
  })

  it('Esc fecha e devolve o foco ao botão', async () => {
    const { trigger } = mountMenu()
    await trigger.trigger('keydown', { key: 'Enter' })
    await nextTick()
    await nextTick()
    menuItems()[0]!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    await nextTick()
    expect(document.body.querySelector('[role="menu"]')).toBeNull()
    expect(document.activeElement).toBe(trigger.element)
  })

  it('clicar num item emite select com o id e fecha', async () => {
    const { wrapper, trigger } = mountMenu()
    await trigger.trigger('click')
    await nextTick()
    menuItems()[2]!.click()
    await nextTick()
    expect(wrapper.emitted('select')).toEqual([['remove']])
    expect(document.body.querySelector('[role="menu"]')).toBeNull()
  })

  it('o item com explicação a mostra no title; os outros ficam sem', async () => {
    const host = document.createElement('div')
    document.body.appendChild(host)
    const wrapper = mount(MoreMenu, {
      props: { label: 'Mais ações', items: [{ id: 'sync', label: 'Atualizar', title: 'Reler o histórico' }, { id: 'edit', label: 'Renomear' }] },
      attachTo: host,
    })
    await wrapper.get('button[aria-haspopup="menu"]').trigger('click')
    await nextTick()
    expect(menuItems()[0]!.getAttribute('title')).toBe('Reler o histórico')
    expect(menuItems()[1]!.hasAttribute('title')).toBe(false)
  })

  it('item desabilitado não emite nem fecha', async () => {
    const { wrapper, trigger } = mountMenu()
    await trigger.trigger('click')
    await nextTick()
    const locked = menuItems()[1]!
    expect(locked.getAttribute('aria-disabled')).toBe('true')
    locked.click()
    await nextTick()
    expect(wrapper.emitted('select')).toBeUndefined()
    expect(document.body.querySelector('[role="menu"]')).not.toBeNull()
  })

  it('clicar fora fecha sem mexer no foco', async () => {
    const { trigger } = mountMenu()
    await trigger.trigger('click')
    await nextTick()
    document.body.dispatchEvent(new Event('pointerdown', { bubbles: true }))
    await nextTick()
    expect(document.body.querySelector('[role="menu"]')).toBeNull()
    expect(document.activeElement).not.toBe(trigger.element)
  })

  it('class e style do pai vão para a raiz; data-test e id ficam no botão', () => {
    const { wrapper, trigger } = mountMenu({ class: 'ml-auto', style: 'margin-top: 2px', 'data-test': 'x', id: 'y' })
    expect(wrapper.classes()).toContain('ml-auto')
    expect(wrapper.attributes('style')).toContain('margin-top')
    expect(trigger.classes()).not.toContain('ml-auto')
    expect(trigger.attributes('style')).toBeUndefined()
    expect(trigger.attributes('data-test')).toBe('x')
    expect(trigger.attributes('id')).toBe('y')
  })

  it('com todos os itens desabilitados, Esc fecha e devolve o foco ao botão', async () => {
    const host = document.createElement('div')
    document.body.appendChild(host)
    const wrapper = mount(MoreMenu, {
      props: { label: 'Mais ações', items: [{ id: 'a', label: 'A', disabled: true }, { id: 'b', label: 'B', disabled: true }] },
      attachTo: host,
    })
    const trigger = wrapper.get('button[aria-haspopup="menu"]')
    await trigger.trigger('keydown', { key: 'Enter' })
    await nextTick()
    await nextTick()
    const panel = document.body.querySelector<HTMLElement>('[role="menu"]')!
    expect(document.activeElement).toBe(panel)
    panel.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    await nextTick()
    expect(document.body.querySelector('[role="menu"]')).toBeNull()
    expect(document.activeElement).toBe(trigger.element)
  })
})
