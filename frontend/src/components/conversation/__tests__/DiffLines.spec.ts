import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import DiffLines from '../DiffLines.vue'

describe('DiffLines com conflito', () => {
  const lines = [
    { kind: 'add' as const, text: '<<<<<<< HEAD', newNo: 1, oldNo: null },
    { kind: 'add' as const, text: 'nosso', newNo: 2, oldNo: null },
    { kind: 'add' as const, text: '=======', newNo: 3, oldNo: null },
    { kind: 'add' as const, text: '>>>>>>> feat', newNo: 4, oldNo: null },
  ]
  it('nomeia as duas branches nas marcas', () => {
    const wrapper = mount(DiffLines, { props: { lines, conflictLabels: { ours: 'develop', theirs: 'feat' } } })
    const rows = wrapper.findAll('[data-test="diff-line"]')
    expect(rows[0].text()).toBe('1<<<<<<< develop (sua branch)')
    expect(rows[3].text()).toBe('4>>>>>>> feat (a que entra)')
    expect(rows.map((r) => r.attributes('data-marker'))).toEqual(['ours', undefined, 'middle', 'theirs'])
  })
  it('sem rótulos fica como antes', () => {
    const wrapper = mount(DiffLines, { props: { lines } })
    expect(wrapper.find('[data-marker]').exists()).toBe(false)
  })
})
