import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import Collapse from '../Collapse.vue'

const mountCollapse = (open: boolean, stubTransition = true) =>
  mount(Collapse, {
    props: { open },
    slots: { default: '<p data-test="inside"><button data-test="inner-button">dentro</button></p>' },
    global: { stubs: { transition: stubTransition } },
  })

describe('Collapse', () => {
  it('fechado não monta o conteúdo, então nada dele recebe foco', () => {
    const w = mountCollapse(false)
    expect(w.find('[data-test="inside"]').exists()).toBe(false)
  })

  it('aberto monta o conteúdo num wrapper de grid com o filho que corta', () => {
    const w = mountCollapse(true)
    expect(w.find('[data-test="inside"]').exists()).toBe(true)
    const grid = w.find('.collapse-grid')
    expect(grid.exists()).toBe(true)
    expect(grid.find('.collapse-inner [data-test="inside"]').exists()).toBe(true)
  })

  it('abre e fecha com o conteúdo montado só enquanto aberto', async () => {
    const w = mountCollapse(false)
    await w.setProps({ open: true })
    expect(w.find('[data-test="inside"]').exists()).toBe(true)
    await w.setProps({ open: false })
    expect(w.find('[data-test="inside"]').exists()).toBe(false)
  })

  it('durante a saída o conteúdo fica inerte, para o Tab não entrar nele', async () => {
    const w = mountCollapse(true, false)
    const grid = w.find('.collapse-grid').element
    await w.setProps({ open: false })
    // Whether it is still leaving or already gone, the element was locked as soon as it began to leave.
    expect(grid.hasAttribute('inert')).toBe(true)
  })
})
