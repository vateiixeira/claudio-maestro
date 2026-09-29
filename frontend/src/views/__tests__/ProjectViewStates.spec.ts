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

describe('tela do projeto em três blocos', () => {
  it('separa em execução, aguardando e finalizadas, e reabre', async () => {
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
    const wrapper = mount(ProjectView, { props: { id: 1 }, global: { plugins: [pinia, createAppRouter(createMemoryHistory())] } })
    await flushPromises()

    const block = (name: string) => wrapper.find(`[data-test="block-${name}"]`)
    expect(block('running').text()).toContain('Em execução')
    expect(block('running').text()).toContain('Rodando')
    expect(block('waiting').text()).toContain('Aguardando você')
    expect(block('waiting').text()).toContain('Esperando')
    expect(block('finished').text()).toContain('Finalizadas')
    expect(block('finished').text()).toContain('Acabou')

    await block('finished').find('[data-test="reopen"]').trigger('click')
    await flushPromises()
    expect(patches).toEqual([{ finished: false }])
    expect(block('waiting').text()).toContain('Acabou')
    expect(block('finished').exists()).toBe(false)
  })
})
