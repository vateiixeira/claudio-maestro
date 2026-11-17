import { afterEach, describe, expect, it } from 'vitest'
import { enableAutoUnmount, mount } from '@vue/test-utils'
import PlanSegments from '../PlanSegments.vue'

enableAutoUnmount(afterEach)

const plan = { path: 'p.md', title: 'Plano', total: 5, done: 2, current: { number: 3, title: 'Revisar a tarefa' } }

describe('PlanSegments', () => {
  it('desenha um segmento por tarefa', () => {
    const wrapper = mount(PlanSegments, { props: { plan } })
    const root = wrapper.get('[data-test="plan-segments"]')
    expect(root.attributes('role')).toBe('img')
    expect(root.attributes('aria-label')).toBe('Tarefa 3 de 5: Revisar a tarefa')
    expect(wrapper.findAll('[data-test="plan-segment"]').map((s) => s.attributes('data-state'))).toEqual(['done', 'done', 'current', 'todo', 'todo'])
    expect(root.text()).toContain('3/5')
  })

  it('acima de 10 tarefas vira uma barra', () => {
    const wrapper = mount(PlanSegments, { props: { plan: { ...plan, total: 12, done: 6, current: { number: 7, title: 'X' } } } })
    expect(wrapper.findAll('[data-test="plan-segment"]')).toHaveLength(0)
    expect(wrapper.get('[data-test="plan-segments-bar"]').attributes('style')).toContain('width: 50%')
  })

  it('parado, os segmentos feitos ficam neutros', () => {
    const running = mount(PlanSegments, { props: { plan } })
    expect(running.findAll('[data-test="plan-segment"]')[0].classes()).toContain('bg-primary')
    const stopped = mount(PlanSegments, { props: { plan, stopped: true } })
    const first = stopped.findAll('[data-test="plan-segment"]')[0]
    expect(first.classes()).toContain('bg-fg-muted')
    expect(first.classes()).not.toContain('bg-primary')
  })
})
