import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { enableAutoUnmount, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import UpdatedNotice from '../UpdatedNotice.vue'
import { useUpdatesStore } from '../../../stores/updates'

enableAutoUnmount(afterEach)
let pinia: Pinia
const BASE = { enabled: true, current: '0.2.0', available: false, latest: null, checked_at: null, releases_url: 'r' }

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  localStorage.removeItem('maestro:update-result-seen')
})

describe('aviso de atualizado', () => {
  it('aparece e some ao dispensar', async () => {
    useUpdatesStore().apply({ ...BASE, last_result: { from: '0.1.0', to: '0.2.0', agentd_changed: false, at: 1 } })
    const w = mount(UpdatedNotice, { global: { plugins: [pinia] } })
    expect(w.get('[data-test="updated-notice"]').text()).toContain('Atualizado para 0.2.0')
    await w.get('[data-test="updated-dismiss"]').trigger('click')
    expect(w.find('[data-test="updated-notice"]').exists()).toBe(false)
  })

  it('não aparece sem resultado', () => {
    useUpdatesStore().apply(BASE)
    expect(mount(UpdatedNotice, { global: { plugins: [pinia] } }).find('[data-test="updated-notice"]').exists()).toBe(false)
  })
})
