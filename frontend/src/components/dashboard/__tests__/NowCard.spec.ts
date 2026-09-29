import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { enableAutoUnmount, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import NowCard from '../NowCard.vue'
import { createAppRouter } from '../../../router'
import { makeSession } from '../../../test/factories'
import type { PlanSummary } from '../../../types/api'

enableAutoUnmount(afterEach)
beforeEach(() => setActivePinia(createPinia()))

const plan: PlanSummary = { path: 'docs/plan.md', title: 'Plano', total: 12, done: 3, current: { number: 4, title: 'Criar o selo' } }

function mountCard(overrides = {}) {
  const router = createAppRouter(createMemoryHistory())
  return mount(NowCard, { props: { session: makeSession({ display_state: 'running', ...overrides }) }, global: { plugins: [router] } })
}

describe('cartão Agora', () => {
  it('mostra a tarefa atual do plano abaixo do título', () => {
    const wrapper = mountCard({ title: 'Construir', plan })
    const line = wrapper.find('[data-test="now-plan"]')

    expect(line.text()).toBe('Tarefa 4 de 12: Criar o selo')
    const html = wrapper.html()
    expect(html.indexOf('Construir')).toBeLessThan(html.indexOf('data-test="now-plan"'))
  })

  it('não mostra a linha sem plano, com plano concluído ou com conversa finalizada', () => {
    expect(mountCard({ plan: null }).find('[data-test="now-plan"]').exists()).toBe(false)
    expect(mountCard({ plan: { ...plan, done: 12, current: null } }).find('[data-test="now-plan"]').exists()).toBe(false)
    expect(mountCard({ display_state: 'finished', finished: true, plan }).find('[data-test="now-plan"]').exists()).toBe(false)
  })
})
