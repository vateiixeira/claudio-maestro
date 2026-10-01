import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import NextNeedsYou from '../NextNeedsYou.vue'
import { createAppRouter } from '../../../router'
import { useSessionsStore } from '../../../stores/sessions'
import { makeSession } from '../../../test/factories'

enableAutoUnmount(afterEach)
let pinia: Pinia

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
})

async function mountButton(current = 's1') {
  const router = createAppRouter(createMemoryHistory())
  await router.push(`/sessions/${current}`)
  const wrapper = mount(NextNeedsYou, { props: { currentId: current }, global: { plugins: [pinia, router] } })
  await flushPromises()
  return { wrapper, router }
}

function seed(...sessions: ReturnType<typeof makeSession>[]) {
  useSessionsStore(pinia).setForProject(1, sessions)
}

describe('botão "Próxima"', () => {
  it('não aparece sem outra conversa aguardando você', async () => {
    seed(
      makeSession({ session_id: 's1', display_state: 'waiting', unread: true }),
      makeSession({ session_id: 's2', display_state: 'waiting', unread: false }),
      makeSession({ session_id: 's3', display_state: 'running', unread: true }),
    )
    const { wrapper } = await mountButton()
    expect(wrapper.find('[data-test="next-needs-you"]').exists()).toBe(false)
  })

  it('conta as outras, sem a atual, e mostra o atalho no title', async () => {
    seed(
      makeSession({ session_id: 's1', display_state: 'waiting', unread: true, last_activity_at: 9 }),
      makeSession({ session_id: 's2', display_state: 'waiting', unread: true, last_activity_at: 8 }),
      makeSession({ session_id: 's3', display_state: 'waiting', pending_kind: 'tool', last_activity_at: 7 }),
    )
    const { wrapper } = await mountButton()
    const button = wrapper.get('[data-test="next-needs-you"]')
    expect(button.text()).toContain('Próxima (2)')
    expect(button.attributes('title')).toContain('(n)')
    expect(button.attributes('title')).toContain('sem contar esta')
    expect(button.attributes('aria-keyshortcuts')).toBe('n')
    expect(button.attributes('aria-label')).toBe('Próxima conversa que aguarda você, 2 outras')
    expect(button.find('svg[aria-hidden="true"]').exists()).toBe(true)
  })

  it('o clique abre a primeira da fila, na ordem da Inbox', async () => {
    seed(
      makeSession({ session_id: 's1', display_state: 'waiting', unread: true, last_activity_at: 9 }),
      makeSession({ session_id: 's3', display_state: 'waiting', unread: true, last_activity_at: 5 }),
      makeSession({ session_id: 's2', display_state: 'waiting', unread: true, last_activity_at: 8 }),
    )
    const { wrapper, router } = await mountButton()
    await wrapper.get('[data-test="next-needs-you"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.fullPath).toBe('/sessions/s2')
  })

  it('segue a ordem da fila em vez de alternar entre as duas primeiras', async () => {
    const all = [
      makeSession({ session_id: 's1', display_state: 'waiting', unread: true, last_activity_at: 9 }),
      makeSession({ session_id: 's2', display_state: 'waiting', unread: true, last_activity_at: 8 }),
      makeSession({ session_id: 's3', display_state: 'waiting', unread: true, last_activity_at: 7 }),
    ]
    for (const [from, to] of [['s1', 's2'], ['s2', 's3'], ['s3', 's1']]) {
      seed(...all)
      const { wrapper, router } = await mountButton(from)
      await wrapper.get('[data-test="next-needs-you"]').trigger('click')
      await flushPromises()
      expect(router.currentRoute.value.fullPath).toBe(`/sessions/${to}`)
      wrapper.unmount()
    }
  })

  it('acompanha a fila quando ela muda', async () => {
    seed(makeSession({ session_id: 's1', display_state: 'waiting', unread: true }))
    const { wrapper } = await mountButton()
    expect(wrapper.find('[data-test="next-needs-you"]').exists()).toBe(false)
    seed(
      makeSession({ session_id: 's1', display_state: 'waiting', unread: true }),
      makeSession({ session_id: 's2', display_state: 'waiting', unread: true }),
    )
    await flushPromises()
    expect(wrapper.get('[data-test="next-needs-you"]').text()).toContain('Próxima (1)')
  })
})
