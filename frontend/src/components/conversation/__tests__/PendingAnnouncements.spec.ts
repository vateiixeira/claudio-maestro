import { afterEach, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import PendingAnnouncements from '../PendingAnnouncements.vue'
import { useSpecialistsStore } from '../../../stores/specialists'
import { jsonResponse, makeSpecialist, routeFetch } from '../../../test/factories'

enableAutoUnmount(afterEach)
afterEach(() => vi.unstubAllGlobals())
it('mostra anúncios pendentes só na principal e os atualiza por evento', async () => {
  const pinia = createPinia()
  setActivePinia(pinia)
  const store = useSpecialistsStore()
  const agent = makeSpecialist({ main_session_id: 'main' })
  store.list = [agent]
  let announcements = [{ id: 1, text: 'Rotina concluída', created_at: 1761391800, session_id: 'run-1', run_id: 1, delivered_at: null }]
  vi.stubGlobal('fetch', routeFetch({
    'GET /api/specialists': () => jsonResponse([agent]),
    'GET /api/agents/1/announcements?pending=true': () => jsonResponse(announcements),
  }))
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/sessions/:id', name: 'session', component: { template: '<div />' } }] })
  await router.push('/sessions/main')
  const w = mount(PendingAnnouncements, { props: { sessionId: 'main' }, global: { plugins: [pinia, router] } })
  await flushPromises()
  expect(w.text()).toContain('Rotina concluída')
  expect(w.get('a').attributes('href')).toBe('/sessions/run-1')
  announcements = []
  store.applyAnnouncement({ specialist_id: 1 })
  await flushPromises()
  expect(w.find('[data-test="announcement-card"]').exists()).toBe(false)
  await w.setProps({ sessionId: 'other' })
  expect(w.text()).toBe('')
})
