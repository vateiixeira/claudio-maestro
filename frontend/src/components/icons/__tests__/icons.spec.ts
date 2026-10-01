import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import IconArrowDown from '../IconArrowDown.vue'
import IconArrowUp from '../IconArrowUp.vue'
import IconBack from '../IconBack.vue'
import IconCheck from '../IconCheck.vue'
import IconChevron from '../IconChevron.vue'
import IconCircle from '../IconCircle.vue'
import IconCircleDot from '../IconCircleDot.vue'
import IconClose from '../IconClose.vue'
import IconExpand from '../IconExpand.vue'
import IconGroup from '../IconGroup.vue'
import IconPlus from '../IconPlus.vue'

const all = { IconArrowDown, IconArrowUp, IconBack, IconCheck, IconChevron, IconCircle, IconCircleDot, IconClose, IconExpand, IconGroup, IconPlus }

describe('ícones em SVG', () => {
  it.each(Object.entries(all))('%s é um SVG em traço, decorativo e do tamanho pedido', (_name, component) => {
    const svg = mount(component, { props: { size: 12 } }).find('svg')
    expect(svg.attributes()).toMatchObject({
      stroke: 'currentColor',
      'stroke-width': '2',
      'stroke-linecap': 'round',
      'stroke-linejoin': 'round',
      fill: 'none',
      'aria-hidden': 'true',
      width: '12',
      height: '12',
    })
  })

  it('o chevron aponta para a direita fechado e gira 90° aberto', () => {
    const closed = mount(IconChevron).find('svg')
    expect(closed.classes()).not.toContain('rotate-90')
    expect(closed.attributes('data-open')).toBe('false')
    const open = mount(IconChevron, { props: { open: true } }).find('svg')
    expect(open.classes()).toContain('rotate-90')
    expect(open.attributes('data-open')).toBe('true')
  })
})
