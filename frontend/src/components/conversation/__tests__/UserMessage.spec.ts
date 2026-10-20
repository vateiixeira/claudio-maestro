import { afterEach, describe, expect, it } from 'vitest'
import { enableAutoUnmount, mount } from '@vue/test-utils'
import UserMessage from '../UserMessage.vue'
import type { UserItem } from '../../../types/conversation'

enableAutoUnmount(afterEach)

const item = (extra: Partial<UserItem> = {}): UserItem => ({ type: 'user', id: 'u1', text: 'Oi do celular', ...extra })

describe('UserMessage', () => {
  it('mensagem do Remote Control leva a marca "via Remote Control"', () => {
    const w = mount(UserMessage, { props: { item: item({ remote: true }) } })
    const mark = w.find('[data-test="remote-mark"]')
    expect(mark.text()).toBe('via Remote Control')
    expect(mark.attributes('title')).toBe('Enviada pelo Remote Control')
  })

  it('mensagem comum não leva a marca', () => {
    expect(mount(UserMessage, { props: { item: item() } }).find('[data-test="remote-mark"]').exists()).toBe(false)
    expect(mount(UserMessage, { props: { item: item({ remote: false }) } }).find('[data-test="remote-mark"]').exists()).toBe(false)
  })
})
