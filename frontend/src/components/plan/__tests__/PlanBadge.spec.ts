import { afterEach, describe, expect, it } from 'vitest'
import { enableAutoUnmount, mount } from '@vue/test-utils'
import PlanBadge from '../PlanBadge.vue'
import { makeSession } from '../../../test/factories'
import type { PlanSummary } from '../../../types/api'

enableAutoUnmount(afterEach)

function makePlan(overrides: Partial<PlanSummary> = {}): PlanSummary {
  return { path: 'docs/plan.md', title: 'Plano', total: 12, done: 3, current: { number: 4, title: 'Criar o selo' }, ...overrides }
}

function mountBadge(session = makeSession({ display_state: 'running', plan: makePlan() })) {
  return mount(PlanBadge, { props: { session } })
}

describe('selo do plano', () => {
  it('mostra "4/12" com barra proporcional e descrição acessível', () => {
    const wrapper = mountBadge()

    expect(wrapper.text()).toContain('4/12')
    expect(wrapper.attributes('title')).toBe('Tarefa 4 de 12: Criar o selo')
    expect(wrapper.attributes('aria-label')).toBe('Tarefa 4 de 12: Criar o selo')
    expect(wrapper.find('[data-test="plan-badge-fill"]').attributes('style')).toContain('width: 25%')
  })

  it('apaga o selo quando a conversa está parada', () => {
    const wrapper = mountBadge(makeSession({ display_state: 'waiting', plan: makePlan() }))

    expect(wrapper.classes()).toContain('opacity-60')
    expect(wrapper.find('[data-test="plan-badge-fill"]').classes()).toContain('bg-fg-muted')
  })

  it('não destaca o selo quando a conversa está rodando', () => {
    const wrapper = mountBadge()

    expect(wrapper.classes()).not.toContain('opacity-60')
    expect(wrapper.find('[data-test="plan-badge-fill"]').classes()).toContain('bg-primary')
  })

  it('não renderiza nada sem plano, com plano concluído ou com conversa finalizada', () => {
    expect(mountBadge(makeSession({ plan: null })).html()).toBe('<!--v-if-->')
    expect(mountBadge(makeSession({ display_state: 'running', plan: makePlan({ done: 12, current: null }) })).html()).toBe('<!--v-if-->')
    expect(mountBadge(makeSession({ display_state: 'finished', finished: true, plan: makePlan() })).html()).toBe('<!--v-if-->')
  })
})
