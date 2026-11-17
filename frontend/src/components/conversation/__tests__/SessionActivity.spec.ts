import { afterEach, describe, expect, it } from 'vitest'
import { enableAutoUnmount, mount } from '@vue/test-utils'
import SessionActivity from '../SessionActivity.vue'
import { makeSession } from '../../../test/factories'

enableAutoUnmount(afterEach)

const plan = { path: 'p.md', title: 'Plano', total: 5, done: 2, current: { number: 3, title: 'Revisar a tarefa' } }

describe('SessionActivity', () => {
  it('comando em mono', () => {
    const wrapper = mount(SessionActivity, { props: { session: makeSession({ display_state: 'running', last_action: 'Bash: pnpm test' }) } })
    const root = wrapper.get('[data-test="session-activity"]')
    expect(root.attributes('data-kind')).toBe('command')
    const mono = root.findAll('.font-mono').find((el) => el.text() === 'pnpm test')
    expect(mono).toBeTruthy()
  })

  it('espera que pede você em laranja', () => {
    const wrapper = mount(SessionActivity, { props: { session: makeSession({ display_state: 'waiting', state: 'awaiting_decision', pending_kind: 'plan', unread: true }) } })
    const root = wrapper.get('[data-test="session-activity"]')
    expect(root.attributes('data-kind')).toBe('waiting')
    expect(root.html()).toContain('text-secondary-soft')
    expect(root.text()).toContain('Plano para aprovar')
  })

  it('plano mostra os segmentos e o título da tarefa', () => {
    const wrapper = mount(SessionActivity, { props: { session: makeSession({ display_state: 'running', plan }) } })
    expect(wrapper.get('[data-test="session-activity"]').attributes('data-kind')).toBe('plan')
    expect(wrapper.find('[data-test="plan-segments"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('Revisar a tarefa')
  })

  it('subagente leva o ícone de agente', () => {
    const wrapper = mount(SessionActivity, { props: { session: makeSession({ display_state: 'running', last_action: 'Agent: Revisar o diff' }) } })
    expect(wrapper.html()).toContain('text-type-agent')
    expect(wrapper.text()).toContain('Revisar o diff')
  })

  it('sem atividade, não renderiza', () => {
    const wrapper = mount(SessionActivity, { props: { session: makeSession({ display_state: 'finished' }) } })
    expect(wrapper.find('[data-test="session-activity"]').exists()).toBe(false)
  })
})
