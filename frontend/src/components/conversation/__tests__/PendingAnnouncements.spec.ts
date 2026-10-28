import { afterEach, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import PendingAnnouncements from '../PendingAnnouncements.vue'
import { useOrgStore } from '../../../stores/org'
import { jsonResponse, makeAgent, routeFetch } from '../../../test/factories'

enableAutoUnmount(afterEach)
afterEach(() => vi.unstubAllGlobals())
it('mostra anúncios pendentes só na principal e os atualiza por evento', async () => {
  const pinia = createPinia()
  setActivePinia(pinia)
  const store = useOrgStore()
  const agent = makeAgent({ main_session_id: 'main' })
  store.agents = [agent]
  let announcements = [{ id: 1, text: 'Rotina concluída', created_at: 1761391800, session_id: 'run-1', run_id: 1, delivered_at: null }]
  vi.stubGlobal('fetch', routeFetch({
    'GET /api/agents/1': () => jsonResponse(agent),
    'GET /api/agents/1/announcements?pending=true': () => jsonResponse(announcements),
  }))
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/sessions/:id', name: 'session', component: { template: '<div />' } }] })
  await router.push('/sessions/main')
  const w = mount(PendingAnnouncements, { props: { sessionId: 'main' }, global: { plugins: [pinia, router] } })
  await flushPromises()
  expect(w.text()).toContain('Rotina concluída')
  expect(w.get('a').attributes('href')).toBe('/sessions/run-1')
  announcements = []
  store.applyEvent('agent.announcement', { agent_id: 1 })
  await flushPromises()
  expect(w.find('[data-test="announcement-card"]').exists()).toBe(false)
  await w.setProps({ sessionId: 'other' })
  expect(w.text()).toBe('')
})
