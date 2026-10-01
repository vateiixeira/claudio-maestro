import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { DOMWrapper, enableAutoUnmount, mount } from '@vue/test-utils'
import OptionMenu from '../OptionMenu.vue'

enableAutoUnmount(afterEach)

const OPTIONS = [
  { value: 'a', label: 'Alfa' },
  { value: 'b', label: 'Beta', description: 'Segunda' },
  { value: 'c', label: 'Gama' },
]

const VIEWPORT = { width: 1000, height: 800 }
let menuHeight = 150
let menuWidth = 200

function rect(left: number, top: number, width = 100, height = 36): DOMRect {
  return { left, top, width, height, right: left + width, bottom: top + height, x: left, y: top, toJSON: () => ({}) } as DOMRect
}

function mountMenu(buttonRect: DOMRect, extra: Record<string, unknown> = {}) {
  const host = document.createElement('div')
  document.body.appendChild(host)
  const wrapper = mount(OptionMenu, {
    props: { name: 'Modelo', text: 'Beta', options: OPTIONS, selected: 'b', ...extra },
    attachTo: host,
  })
  const trigger = wrapper.find('button[aria-label="Modelo"]')
  vi.spyOn(trigger.element, 'getBoundingClientRect').mockReturnValue(buttonRect)
  return { wrapper, trigger, host }
}

/** The button ends up above the viewport, as if an ancestor scrolled it away. */
function scrollButtonOut(trigger: { element: Element }) {
  vi.mocked(trigger.element.getBoundingClientRect).mockReturnValue(rect(50, -100))
}
function scrollButtonBack(trigger: { element: Element }) {
  vi.mocked(trigger.element.getBoundingClientRect).mockReturnValue(rect(50, 700))
}

const body = () => new DOMWrapper(document.body)
const menuEl = () => document.body.querySelector<HTMLElement>('[role="menu"]')

beforeEach(() => {
  menuHeight = 150
  menuWidth = 200
  vi.stubGlobal('innerWidth', VIEWPORT.width)
  vi.stubGlobal('innerHeight', VIEWPORT.height)
  vi.spyOn(HTMLElement.prototype, 'scrollHeight', 'get').mockImplementation(() => menuHeight)
  vi.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockImplementation(() => menuWidth)
})
afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})

describe('OptionMenu', () => {
  it('renders the panel in document.body, outside the component container', async () => {
    const { wrapper, trigger, host } = mountMenu(rect(50, 700))
    expect(menuEl()).toBeNull()
    await trigger.trigger('click')
    const menu = menuEl()
    expect(menu).not.toBeNull()
    expect(host.contains(menu)).toBe(false)
    expect(wrapper.element.contains(menu)).toBe(false)
    expect(menu!.parentElement).toBe(document.body)
    expect(trigger.attributes('aria-expanded')).toBe('true')
    expect(trigger.attributes('aria-haspopup')).toBe('menu')
    expect(menu!.getAttribute('aria-label')).toBe('Modelo')
    expect(menu!.className).toContain('z-[60]')
  })

  it('opens upward with position fixed when there is room above', async () => {
    const { trigger } = mountMenu(rect(50, 700))
    await trigger.trigger('click')
    const style = menuEl()!.style
    expect(style.position).toBe('fixed')
    // Anchored by the bottom edge: viewport height - button top + 4px gap.
    expect(style.bottom).toBe(`${800 - 700 + 4}px`)
    expect(style.top).toBe('')
    expect(style.left).toBe('50px')
    // Space above the button (700) minus the gap (4) and the margin (8).
    expect(style.maxHeight).toBe(`${700 - 4 - 8}px`)
  })

  it('opens downward when it does not fit above but fits below', async () => {
    const { trigger } = mountMenu(rect(50, 40))
    await trigger.trigger('click')
    const style = menuEl()!.style
    expect(style.position).toBe('fixed')
    expect(style.top).toBe(`${40 + 36 + 4}px`)
    expect(style.bottom).toBe('')
    expect(style.maxHeight).toBe(`${800 - 76 - 4 - 8}px`)
  })

  it('picks the side with more room and limits the height when it fits on neither', async () => {
    menuHeight = 900
    const { trigger } = mountMenu(rect(50, 500))
    await trigger.trigger('click')
    const style = menuEl()!.style
    // Above: 500 - 12 = 488. Below: 800 - 536 - 12 = 252. Picks above.
    expect(style.bottom).toBe(`${800 - 500 + 4}px`)
    expect(style.maxHeight).toBe('488px')
    expect(menuEl()!.className).toContain('overflow-y-auto')
  })

  it('goes below with limited height when that side is larger and nothing fits', async () => {
    menuHeight = 900
    const { trigger } = mountMenu(rect(50, 200))
    await trigger.trigger('click')
    const style = menuEl()!.style
    expect(style.top).toBe(`${200 + 36 + 4}px`)
    expect(style.maxHeight).toBe(`${800 - 236 - 4 - 8}px`)
  })

  it('keeps the panel inside the viewport horizontally', async () => {
    const { trigger } = mountMenu(rect(950, 700))
    await trigger.trigger('click')
    expect(menuEl()!.style.left).toBe(`${1000 - 200 - 8}px`)
    await trigger.trigger('click')
    expect(menuEl()).toBeNull()

    vi.mocked(trigger.element.getBoundingClientRect).mockReturnValue(rect(-30, 700))
    await trigger.trigger('click')
    expect(menuEl()!.style.left).toBe('8px')
  })

  it('selects when clicking inside the teleported panel, which is not an outside click', async () => {
    const { wrapper, trigger } = mountMenu(rect(50, 700))
    await trigger.trigger('click')
    const panelItem = menuEl()!.querySelectorAll<HTMLElement>('[role="menuitemradio"]')[0]!
    panelItem.dispatchEvent(new Event('pointerdown', { bubbles: true }))
    await wrapper.vm.$nextTick()
    // pointerdown inside the panel leaves the menu open.
    expect(menuEl()).not.toBeNull()
    await new DOMWrapper(panelItem).trigger('click')
    expect(wrapper.emitted('select')).toEqual([['a']])
    expect(menuEl()).toBeNull()
  })

  it('does not treat pointerdown on the button as outside', async () => {
    const { wrapper, trigger } = mountMenu(rect(50, 700))
    await trigger.trigger('click')
    trigger.element.dispatchEvent(new Event('pointerdown', { bubbles: true }))
    await wrapper.vm.$nextTick()
    expect(menuEl()).not.toBeNull()
  })

  it('closes on an outside click', async () => {
    const { wrapper, trigger } = mountMenu(rect(50, 700))
    await trigger.trigger('click')
    document.body.dispatchEvent(new Event('pointerdown', { bubbles: true }))
    await wrapper.vm.$nextTick()
    expect(menuEl()).toBeNull()
    expect(trigger.attributes('aria-expanded')).toBe('false')
  })

  it('Esc closes the menu without propagating, and returns focus to the button', async () => {
    const { trigger } = mountMenu(rect(50, 700))
    const outer = vi.fn()
    document.addEventListener('keydown', outer)
    await trigger.trigger('click')
    await body().find('[role="menu"]').trigger('keydown', { key: 'Escape' })
    document.removeEventListener('keydown', outer)
    expect(outer).not.toHaveBeenCalled()
    expect(menuEl()).toBeNull()
    expect(document.activeElement).toBe(trigger.element)
  })

  it('Tab closes the menu and leaves the focus on the button', async () => {
    const { trigger } = mountMenu(rect(50, 700))
    await trigger.trigger('click')
    expect(menuEl()!.contains(document.activeElement)).toBe(true)
    const event = new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true })
    menuEl()!.dispatchEvent(event)
    await new Promise((r) => setTimeout(r, 0))
    expect(event.defaultPrevented).toBe(false)
    expect(menuEl()).toBeNull()
    expect(document.activeElement).toBe(trigger.element)
  })

  it('returns the focus to the button on resize or scroll only when it was inside the panel', async () => {
    const { wrapper, trigger, host } = mountMenu(rect(50, 700))
    const elsewhere = document.createElement('input')
    document.body.appendChild(elsewhere)

    await trigger.trigger('click')
    expect(menuEl()!.contains(document.activeElement)).toBe(true)
    window.dispatchEvent(new Event('resize'))
    await wrapper.vm.$nextTick()
    expect(menuEl()).toBeNull()
    expect(document.activeElement).toBe(trigger.element)

    await trigger.trigger('click')
    scrollButtonOut(trigger)
    host.dispatchEvent(new Event('scroll'))
    await wrapper.vm.$nextTick()
    expect(menuEl()).toBeNull()
    expect(document.activeElement).toBe(trigger.element)
    scrollButtonBack(trigger)

    await trigger.trigger('click')
    elsewhere.focus()
    window.dispatchEvent(new Event('resize'))
    await wrapper.vm.$nextTick()
    expect(menuEl()).toBeNull()
    expect(document.activeElement).toBe(elsewhere)

    await trigger.trigger('click')
    elsewhere.focus()
    scrollButtonOut(trigger)
    host.dispatchEvent(new Event('scroll'))
    await wrapper.vm.$nextTick()
    expect(menuEl()).toBeNull()
    expect(document.activeElement).toBe(elsewhere)
  })

  it('closes when the window is resized', async () => {
    const { wrapper, trigger } = mountMenu(rect(50, 700))
    await trigger.trigger('click')
    window.dispatchEvent(new Event('resize'))
    await wrapper.vm.$nextTick()
    expect(menuEl()).toBeNull()
  })

  it('ignores scrolling of the panel itself', async () => {
    const { wrapper, trigger } = mountMenu(rect(50, 700))
    await trigger.trigger('click')
    const before = menuEl()!.style.cssText
    menuEl()!.dispatchEvent(new Event('scroll'))
    await wrapper.vm.$nextTick()
    expect(menuEl()).not.toBeNull()
    expect(menuEl()!.style.cssText).toBe(before)
  })

  it('ignores scrolling of an element that does not contain the button, without touching the focus', async () => {
    const { wrapper, trigger } = mountMenu(rect(50, 700))
    const sibling = document.createElement('div')
    document.body.appendChild(sibling)
    await trigger.trigger('click')
    const focused = document.activeElement
    expect(menuEl()!.contains(focused)).toBe(true)
    const before = menuEl()!.style.cssText
    sibling.dispatchEvent(new Event('scroll'))
    await wrapper.vm.$nextTick()
    expect(menuEl()).not.toBeNull()
    expect(trigger.attributes('aria-expanded')).toBe('true')
    expect(document.activeElement).toBe(focused)
    expect(menuEl()!.style.cssText).toBe(before)
  })

  it('repositions, instead of closing, when an ancestor of the button scrolls and the button stays visible', async () => {
    const { wrapper, trigger, host } = mountMenu(rect(50, 700))
    await trigger.trigger('click')
    const focused = document.activeElement
    expect(menuEl()!.style.bottom).toBe(`${800 - 700 + 4}px`)
    vi.mocked(trigger.element.getBoundingClientRect).mockReturnValue(rect(60, 500))
    host.dispatchEvent(new Event('scroll'))
    await wrapper.vm.$nextTick()
    expect(menuEl()).not.toBeNull()
    expect(document.activeElement).toBe(focused)
    expect(menuEl()!.style.bottom).toBe(`${800 - 500 + 4}px`)
    expect(menuEl()!.style.left).toBe('60px')
  })

  it('repositions when the page itself scrolls', async () => {
    const { wrapper, trigger } = mountMenu(rect(50, 700))
    await trigger.trigger('click')
    vi.mocked(trigger.element.getBoundingClientRect).mockReturnValue(rect(50, 600))
    document.dispatchEvent(new Event('scroll'))
    await wrapper.vm.$nextTick()
    expect(menuEl()).not.toBeNull()
    expect(menuEl()!.style.bottom).toBe(`${800 - 600 + 4}px`)
  })

  it('closes when an ancestor scrolls the button out of the viewport', async () => {
    const { wrapper, trigger, host } = mountMenu(rect(50, 700))
    await trigger.trigger('click')
    scrollButtonOut(trigger)
    host.dispatchEvent(new Event('scroll'))
    await wrapper.vm.$nextTick()
    expect(menuEl()).toBeNull()
    expect(trigger.attributes('aria-expanded')).toBe('false')
  })

  it('removes the listeners when it closes and when it unmounts', async () => {
    const add = vi.spyOn(window, 'addEventListener')
    const remove = vi.spyOn(window, 'removeEventListener')
    const docAdd = vi.spyOn(document, 'addEventListener')
    const docRemove = vi.spyOn(document, 'removeEventListener')
    const { wrapper, trigger } = mountMenu(rect(50, 700))
    await trigger.trigger('click')
    const added = [...add.mock.calls, ...docAdd.mock.calls].map((c) => c[0]).filter((t) => ['resize', 'scroll', 'pointerdown'].includes(t as string))
    expect(added.sort()).toEqual(['pointerdown', 'resize', 'scroll'])
    await trigger.trigger('click')
    const removed = [...remove.mock.calls, ...docRemove.mock.calls].map((c) => c[0]).filter((t) => ['resize', 'scroll', 'pointerdown'].includes(t as string))
    expect(removed.sort()).toEqual(['pointerdown', 'resize', 'scroll'])

    await trigger.trigger('click')
    remove.mockClear()
    docRemove.mockClear()
    wrapper.unmount()
    const afterUnmount = [...remove.mock.calls, ...docRemove.mock.calls].map((c) => c[0])
    expect(afterUnmount).toEqual(expect.arrayContaining(['pointerdown', 'resize', 'scroll']))
    expect(menuEl()).toBeNull()
  })

  it('focuses the selected option on open and navigates with the arrows', async () => {
    const { trigger } = mountMenu(rect(50, 700))
    await trigger.trigger('click')
    expect(document.activeElement?.textContent).toContain('Beta')
    await body().find('[role="menu"]').trigger('keydown', { key: 'ArrowDown' })
    expect(document.activeElement?.textContent).toContain('Gama')
    await body().find('[role="menu"]').trigger('keydown', { key: 'Home' })
    expect(document.activeElement?.textContent).toContain('Alfa')
    const checked = menuEl()!.querySelectorAll('[role="menuitemradio"][aria-checked="true"]')
    expect(checked).toHaveLength(1)
  })

  it('bolds only the label of the selected option, not its description', async () => {
    const { trigger } = mountMenu(rect(50, 700))
    await trigger.trigger('click')
    for (const item of Array.from(menuEl()!.querySelectorAll<HTMLElement>('[role="menuitemradio"]'))) {
      expect(item.className).not.toContain('aria-checked:font-semibold')
      expect(item.querySelector('[data-test="option-label"]')!.className).toContain('group-aria-checked:font-semibold')
      expect(item.className).toMatch(/(^|\s)group(\s|$)/)
      expect(item.querySelector('[data-test="option-description"]')?.className ?? '').not.toContain('font-semibold')
    }
  })

  it('marks only the selected option with a check icon and keeps aria-checked', async () => {
    const { trigger } = mountMenu(rect(50, 700))
    await trigger.trigger('click')
    const items = Array.from(menuEl()!.querySelectorAll<HTMLElement>('[role="menuitemradio"]'))
    expect(items.map((i) => !!i.querySelector('[data-test="option-check"]'))).toEqual([false, true, false])
    expect(items.map((i) => i.getAttribute('aria-checked'))).toEqual(['false', 'true', 'false'])
    const check = items[1]!.querySelector('svg')!
    expect(check.getAttribute('aria-hidden')).toBe('true')
    expect(check.getAttribute('stroke')).toBe('currentColor')
    // Every item reserves the same slot so the labels stay aligned.
    expect(items.every((i) => i.querySelector('[data-test="option-mark"]'))).toBe(true)
  })

  it('shows the prefix before the text, in a subtle tone', () => {
    const { trigger } = mountMenu(rect(50, 700), { prefix: 'Permissões:' })
    expect(trigger.text()).toBe('Permissões: Beta')
    expect(trigger.find('[data-test="option-prefix"]').classes()).toContain('text-fg-subtle')
  })

  it('renders the label and the description of an option in separate elements', async () => {
    const { trigger } = mountMenu(rect(50, 700))
    await trigger.trigger('click')
    const beta = menuEl()!.querySelectorAll<HTMLElement>('[role="menuitemradio"]')[1]!
    expect(beta.querySelector('[data-test="option-label"]')!.textContent).toBe('Beta')
    expect(beta.querySelector('[data-test="option-description"]')!.textContent).toBe('Segunda')
  })
})
