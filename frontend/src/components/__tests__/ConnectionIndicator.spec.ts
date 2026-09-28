import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ConnectionIndicator from '../ConnectionIndicator.vue'

describe('indicador de conexão', () => {
  it('só aparece quando a conexão caiu', () => {
    for (const status of ['idle', 'connecting', 'connected'] as const) {
      expect(mount(ConnectionIndicator, { props: { status } }).find('[role="status"]').exists()).toBe(false)
    }
    const wrapper = mount(ConnectionIndicator, { props: { status: 'reconnecting' } })
    expect(wrapper.find('[role="status"]').text()).toContain('Sem conexão com o servidor')
  })
})
