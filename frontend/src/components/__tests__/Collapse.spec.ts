import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import Collapse from '../Collapse.vue'
import { COLLAPSE_OPENING_KEY } from '../../conversation/collapseActivity'

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

describe('Collapse avisa quando começa a abrir', () => {
  const mountWithListener = (open: boolean) => {
    const opening = vi.fn()
    const w = mount(Collapse, {
      props: { open },
      slots: { default: '<p>dentro</p>' },
      global: { stubs: { transition: false }, provide: { [COLLAPSE_OPENING_KEY as symbol]: opening } },
    })
    return { w, opening }
  }

  it('avisa a cada abertura, e não ao montar aberto nem ao fechar', async () => {
    const { w, opening } = mountWithListener(true)
    expect(opening).not.toHaveBeenCalled()
    await w.setProps({ open: false })
    expect(opening).not.toHaveBeenCalled()
    await w.setProps({ open: true })
    expect(opening).toHaveBeenCalledTimes(1)
  })

  it('sem quem escute, funciona do mesmo jeito', async () => {
    const w = mountCollapse(false, false)
    await w.setProps({ open: true })
    expect(w.find('[data-test="inside"]').exists()).toBe(true)
  })
})
