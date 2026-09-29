import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ColumnResizer from '../ColumnResizer.vue'

describe('alça de largura', () => {
  it('informa o máximo e não mexe no body ao desmontar sem arrastar', () => {
    const w = mount(ColumnResizer, { props: { width: 500, label: 'Ajustar' } })
    expect(w.attributes('aria-valuemax')).toBeDefined()
    document.body.style.cursor = 'wait'
    w.unmount()
    expect(document.body.style.cursor).toBe('wait')
    document.body.style.removeProperty('cursor')
  })

  it('limpa o body ao desmontar durante o arrasto', () => {
    const w = mount(ColumnResizer, { props: { width: 500, label: 'Ajustar' } })
    w.element.dispatchEvent(new MouseEvent('pointerdown', { clientX: 10, button: 0, bubbles: true }))
    expect(document.body.style.cursor).toBe('col-resize')
    w.unmount()
    expect(document.body.style.cursor).toBe('')
  })
})
