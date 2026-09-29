import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import { createAppRouter } from '../../../router'
import { jsonResponse, makeProject, makeSession, makeSnapshot, routeFetch } from '../../../test/factories'
import { useProjectsStore } from '../../../stores/projects'
import { useSessionsStore } from '../../../stores/sessions'

vi.mock('../../../api/socket', () => ({
  useEventSocket: () => ({ onSession: () => () => {}, onReconnect: () => () => {} }),
}))

import SessionColumn from '../SessionColumn.vue'

enableAutoUnmount(afterEach)
let pinia: Pinia
beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  const projects = useProjectsStore(pinia)
  projects.projects = [makeProject({ id: 1 })]
  projects.loaded = true
  useSessionsStore(pinia).setForProject(1, [makeSession({ session_id: 's1', title: 'Antigo' })])
})
afterEach(() => vi.unstubAllGlobals())

async function mountColumn(patch: (body: Record<string, unknown>) => Response) {
  const bodies: Record<string, unknown>[] = []
  vi.stubGlobal('fetch', routeFetch({
    'GET /api/sessions/s1': () => jsonResponse(makeSnapshot({ title: 'Antigo' })),
    'POST /api/sessions/s1/seen': () => jsonResponse(undefined, 204),
    'PATCH /api/sessions/s1': (init) => {
      const body = JSON.parse(String(init?.body))
      bodies.push(body)
      return patch(body)
    },
  }))
  const router = createAppRouter(createMemoryHistory())
  await router.push('/sessions/s1')
  const w = mount(SessionColumn, { props: { id: 's1' }, global: { plugins: [pinia, router] } })
  await flushPromises()
  return { w, bodies }
}

describe('cabeçalho da coluna', () => {
  it('finaliza e reabre', async () => {
    const { w, bodies } = await mountColumn((b) =>
      jsonResponse(makeSession({ session_id: 's1', seq: bodies_len(), finished: !!b.finished, display_state: b.finished ? 'finished' : 'waiting' })),
    )
    await w.find('[data-test="toggle-finished"]').trigger('click')
    await flushPromises()
    expect(w.find('[data-test="toggle-finished"]').text()).toBe('Reabrir')
    await w.find('[data-test="toggle-finished"]').trigger('click')
    await flushPromises()
    expect(w.find('[data-test="toggle-finished"]').text()).toBe('Finalizar')
    expect(bodies).toEqual([{ finished: true }, { finished: false }])
  })

  it('renomeia com Enter', async () => {
    const { w, bodies } = await mountColumn((b) => jsonResponse(makeSession({ session_id: 's1', seq: 1, title: String(b.title) })))
    await w.find('[data-test="session-title"]').trigger('click')
    const input = w.find('[data-test="title-input"]')
    await input.setValue('Novo nome')
    await input.trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(bodies).toEqual([{ title: 'Novo nome' }])
    expect(w.find('[data-test="title-input"]').exists()).toBe(false)
    expect(w.find('[data-test="session-title"]').text()).toBe('Novo nome')
  })

  it('Esc cancela sem salvar', async () => {
    const { w, bodies } = await mountColumn(() => jsonResponse(makeSession()))
    await w.find('[data-test="rename-session"]').trigger('click')
    const input = w.find('[data-test="title-input"]')
    await input.setValue('Outro')
    await input.trigger('keydown', { key: 'Escape' })
    expect(bodies).toEqual([])
    expect(w.find('[data-test="session-title"]').text()).toBe('Antigo')
  })

  it('mostra o detail do erro', async () => {
    const { w } = await mountColumn(() => jsonResponse({ detail: 'Título longo demais.' }, 422))
    await w.find('[data-test="session-title"]').trigger('click')
    await w.find('[data-test="title-input"]').trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(w.find('[role="alert"]').text()).toContain('Título longo demais.')
    expect(w.find('[data-test="title-input"]').exists()).toBe(true)
  })
})

let counter = 0
function bodies_len() {
  return ++counter
}
