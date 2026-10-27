import { expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import ReviewRecord from '../ReviewRecord.vue'
it('parecer antigo preserva autor, revisor e motivo sem aparentar aprovação atual', () => {
  const router = createRouter({ history: createMemoryHistory(), routes: [] })
  const wrapper = mount(ReviewRecord, { props: { review: { id: 4, status: 'stale', author_attempt_id: 11, review_attempt_id: 12, input_revision: 3, reason: 'O alvo mudou depois da revisão.' } }, global: { plugins: [router] } })
  expect(wrapper.text()).toContain('Desatualizada')
  expect(wrapper.text()).toContain('O alvo mudou depois da revisão.')
  expect(wrapper.get('a[href="#attempt-11"]').text()).toContain('11')
  expect(wrapper.get('a[href="#attempt-12"]').text()).toContain('12')
})
