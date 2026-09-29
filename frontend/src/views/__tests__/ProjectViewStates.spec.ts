import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import ProjectView from '../ProjectView.vue'
import { createAppRouter } from '../../router'
import { useProjectsStore } from '../../stores/projects'
import { jsonResponse, makeProject, makeSession, routeFetch } from '../../test/factories'

enableAutoUnmount(afterEach)
let pinia: Pinia
beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  const projects = useProjectsStore(pinia)
  projects.projects = [makeProject({ id: 1 })]
  projects.loaded = true
})
afterEach(() => vi.unstubAllGlobals())

async function mountProject() {
  const wrapper = mount(ProjectView, { props: { id: 1 }, global: { plugins: [pinia, createAppRouter(createMemoryHistory())] } })
  await flushPromises()
  return wrapper
}

const rowOf = (wrapper: ReturnType<typeof mount>, title: string) =>
  wrapper.findAll('[data-test="conversation-row"]').find((r) => r.text().includes(title))!

describe('tela do projeto com a linha de conversa', () => {
  it('mostra todas as conversas na mesma lista, sem blocos por estado, e reabre pela linha', async () => {
    const patches: unknown[] = []
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/projects/1/sessions': () => jsonResponse([
        makeSession({ session_id: 'r', title: 'Rodando', display_state: 'running', state: 'running' }),
        makeSession({ session_id: 'w', title: 'Esperando', display_state: 'waiting' }),
        makeSession({ session_id: 'f', title: 'Acabou', display_state: 'finished', finished: true }),
      ]),
      'PATCH /api/sessions/f': (init) => {
        patches.push(JSON.parse(String(init?.body)))
        return jsonResponse(makeSession({ session_id: 'f', title: 'Acabou', seq: 9, display_state: 'waiting' }))
      },
    }))
    const wrapper = await mountProject()

    expect(wrapper.findAll('[data-test="row-link"]').map((r) => r.text())).toEqual(['Rodando', 'Esperando', 'Acabou'])
    expect(wrapper.find('[data-test="block-running"]').exists()).toBe(false)
    expect(wrapper.find('#finalizadas').exists()).toBe(false)

    await rowOf(wrapper, 'Acabou').find('[data-test="row-reopen"]').trigger('click')
    await flushPromises()
    expect(patches).toEqual([{ finished: false }])
    expect(rowOf(wrapper, 'Acabou').find('[data-test="row-reopen"]').exists()).toBe(false)
    expect(rowOf(wrapper, 'Acabou').find('[data-test="row-finish"]').exists()).toBe(true)
  })

  it('Finalizar só nas que não estão finalizadas, Reabrir só na finalizada, e sem estados internos', async () => {
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/projects/1/sessions': () => jsonResponse([
        makeSession({ session_id: 'r', title: 'Rodando', display_state: 'running', state: 'running' }),
        makeSession({ session_id: 'w', title: 'Esperando', display_state: 'waiting', state: 'idle' }),
        makeSession({ session_id: 'c', title: 'Fechadinha', display_state: 'waiting', state: 'closed' }),
        makeSession({ session_id: 'f', title: 'Acabou', display_state: 'finished', finished: true, state: 'closed' }),
      ]),
    }))
    const wrapper = await mountProject()

    expect(wrapper.findAll('[data-test="row-finish"]')).toHaveLength(3)
    expect(wrapper.findAll('[data-test="row-reopen"]')).toHaveLength(1)
    expect(rowOf(wrapper, 'Acabou').find('[data-test="row-reopen"]').exists()).toBe(true)
    expect(wrapper.text()).not.toContain('Parada')
    expect(wrapper.text()).not.toContain('Fechada')
  })

  it('mostra na página o erro de uma ação da linha', async () => {
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/projects/1/sessions': () => jsonResponse([
        makeSession({ session_id: 'f', title: 'Acabou', display_state: 'finished', finished: true }),
      ]),
      'PATCH /api/sessions/f': () => jsonResponse({ detail: 'Não foi possível reabrir.' }, 500),
    }))
    const wrapper = await mountProject()

    await rowOf(wrapper, 'Acabou').find('[data-test="row-reopen"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[role="alert"]').text()).toContain('Não foi possível reabrir.')
  })
})
