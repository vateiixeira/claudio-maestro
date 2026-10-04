import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ClosureBadge from '../ClosureBadge.vue'

const s = (closure_verdict: string | null, display_state = 'waiting') => ({ closure_verdict, display_state }) as never

describe('ClosureBadge', () => {
  it('shows the label', () => {
    const w = mount(ClosureBadge, { props: { session: s('user_action') } })
    expect(w.get('[data-test="closure-badge"]').text()).toBe('Falta ação sua')
  })
  it('compact shows only a dot with an accessible name', () => {
    const w = mount(ClosureBadge, { props: { session: s('can_close'), compact: true } })
    const dot = w.get('[data-test="closure-dot"]')
    expect(dot.attributes('aria-label')).toBe('Pode fechar')
    expect(dot.attributes('title')).toBe('Pode fechar')
    expect(w.find('[data-test="closure-badge"]').exists()).toBe(false)
  })
  it.each([[null], ['in_progress']])('renders nothing for %s', (v) => {
    expect(mount(ClosureBadge, { props: { session: s(v) } }).html()).toBe('<!--v-if-->')
  })
  it('renders nothing for a running session', () => {
    expect(mount(ClosureBadge, { props: { session: s('can_close', 'running') } }).html()).toBe('<!--v-if-->')
  })
  it('renders nothing for a finished session', () => {
    expect(mount(ClosureBadge, { props: { session: s('can_close', 'finished') } }).html()).toBe('<!--v-if-->')
  })
})
