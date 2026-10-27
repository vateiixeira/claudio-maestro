import { expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import TaskPullRequests from '../TaskPullRequests.vue'
it('mostra PR, autoria original e feedback incerto sem confundir com entrega ao executor', () => {
  const wrapper = mount(TaskPullRequests, { props: { page: { total: 30, limit: 25, items: [{ url: 'https://github.com/demo/projeto/pull/3', origin_attempt_id: 11, last_attempt_id: 12, origin_session_id: 'old', last_session_id: 'new', created_at: 100, polled_at: 200, closed: false, head_sha: 'abc123', comments: { queued: 2, dispatching: 0, delivered: 1, uncertain: 1 }, latest_feedback_attempt_id: 13 }] } } })
  expect(wrapper.get('a[href="https://github.com/demo/projeto/pull/3"]').attributes('rel')).toContain('noopener')
  expect(wrapper.get('a[href="#attempt-11"]').text()).toContain('11')
  expect(wrapper.get('a[href="#attempt-12"]').text()).toContain('12')
  expect(wrapper.get('a[href="#attempt-13"]').text()).toContain('13')
  expect(wrapper.text()).toContain('1 envio incerto')
  expect(wrapper.text()).toContain('2 comentários na fila')
  expect(wrapper.text()).toContain('1 de 30')
})
