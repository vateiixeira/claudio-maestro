import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import SidebarLane from '../SidebarLane.vue'
import { createAppRouter } from '../../../router'
import { useProjectsStore } from '../../../stores/projects'
import { useSessionsStore } from '../../../stores/sessions'
import { isSectionOpened, setSectionCollapsed, setSectionOpened } from '../../../sidebarCollapse'
import { makeProject, makeSession } from '../../../test/factories'

enableAutoUnmount(afterEach)
let pinia: Pinia

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  useProjectsStore(pinia).projects = [makeProject({ id: 1 })]
  setSectionCollapsed('review', false)
  setSectionOpened('later', false)
})

async function mountLane(props: { lane: 'review' | 'later'; title: string; startCollapsed?: boolean }) {
  const router = createAppRouter(createMemoryHistory())
  await router.push('/inbox')
  await router.isReady()
  const wrapper = mount(SidebarLane, { props, global: { plugins: [pinia, router] } })
  await flushPromises()
  return wrapper
}

describe('faixas Para revisar e Depois', () => {
  it('Para revisar lista as marcadas para revisão, com contagem', async () => {
    useSessionsStore(pinia).setForProject(1, [
      makeSession({ session_id: 'r1', mark: 'review' }),
      makeSession({ session_id: 'r2', mark: 'review' }),
      makeSession({ session_id: 'c' }),
    ])
    const w = await mountLane({ lane: 'review', title: 'Para revisar' })
    expect(w.find('[data-test="lane-review-count"]').text()).toBe('2')
    expect(w.findAll('[data-test="lane-review-row"]')).toHaveLength(2)
  })

  it('some quando não há nenhuma', async () => {
    useSessionsStore(pinia).setForProject(1, [makeSession({ session_id: 'c' })])
    const w = await mountLane({ lane: 'review', title: 'Para revisar' })
    expect(w.find('[data-test="lane-review"]').exists()).toBe(false)
  })

  it('Depois começa recolhida e lembra quando abre', async () => {
    useSessionsStore(pinia).setForProject(1, [
      makeSession({ session_id: 'e', mark: 'on_hold' }),
      makeSession({ session_id: 'b', mark: 'blocked' }),
    ])
    const w = await mountLane({ lane: 'later', title: 'Depois', startCollapsed: true })
    expect(w.find('[data-test="lane-later-count"]').text()).toBe('2')
    expect(w.findAll('[data-test="lane-later-row"]')).toHaveLength(0)
    await w.find('[data-test="lane-later-toggle"]').trigger('click')
    expect(w.findAll('[data-test="lane-later-row"]')).toHaveLength(2)
    expect(isSectionOpened('later')).toBe(true)
  })
})
