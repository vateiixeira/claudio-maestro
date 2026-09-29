import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import AllSessionsView from '../AllSessionsView.vue'
import { createAppRouter } from '../../router'
import { useProjectsStore } from '../../stores/projects'
import { useSessionsStore } from '../../stores/sessions'
import { jsonResponse, makeEvent, makeProject, makeSession, routeFetch } from '../../test/factories'

enableAutoUnmount(afterEach)
let pinia: Pinia
beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  const projects = useProjectsStore(pinia)
  projects.projects = [makeProject({ id: 1, name: 'loja' }), makeProject({ id: 2, name: 'blog' })]
  projects.loaded = true
})
afterEach(() => vi.unstubAllGlobals())

describe('todas as sessões', () => {
  it('mostra três colunas, filtra por projeto e abre a sessão', async () => {
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/projects/1/sessions': () => jsonResponse([
        makeSession({ session_id: 'a', title: 'Loja rodando', display_state: 'running' }),
        makeSession({ session_id: 'b', title: 'Loja acabou', display_state: 'finished', finished: true }),
      ]),
      'GET /api/projects/2/sessions': () => jsonResponse([
        makeSession({ session_id: 'c', project_id: 2, title: 'Blog esperando', display_state: 'waiting' }),
      ]),
    }))
    const router = createAppRouter(createMemoryHistory())
    await router.push('/sessions')
    const wrapper = mount(AllSessionsView, { global: { plugins: [pinia, router] } })
    await flushPromises()

    const col = (name: string) => wrapper.find(`[data-test="column-${name}"]`)
    expect(col('running').text()).toContain('Loja rodando')
    expect(col('waiting').text()).toContain('Blog esperando')
    expect(col('finished').text()).toContain('Loja acabou')

    const filters = wrapper.findAll('[data-test="filter"]')
    expect(filters.map((f) => f.text())).toEqual(['Todos os projetos', 'loja', 'blog'])
    await filters[2]!.trigger('click')
    expect(filters[2]!.attributes('aria-pressed')).toBe('true')
    expect(col('waiting').text()).toContain('Blog esperando')
    expect(col('running').text()).not.toContain('Loja rodando')

    await wrapper.find('[data-test="open-session"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.fullPath).toBe('/sessions/c')
  })

  it('responde a permissão pendente no cartão e ele sai da coluna quando o resumo chega', async () => {
    const answers: unknown[] = []
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/projects/1/sessions': () => jsonResponse([
        makeSession({
          session_id: 'a', title: 'Pede Bash', display_state: 'waiting', awaiting_decision: true,
          pending_permission: { prompt_id: 'p1', tool_name: 'Bash', summary: 'pytest -k pix', can_allow_always: false },
        }),
        makeSession({ session_id: 'b', title: 'Pergunta', display_state: 'waiting', awaiting_decision: true, pending_permission: null }),
      ]),
      'GET /api/projects/2/sessions': () => jsonResponse([]),
      'POST /api/sessions/a/prompts/p1': (init) => {
        answers.push(JSON.parse(init!.body as string))
        return jsonResponse({})
      },
    }))
    const router = createAppRouter(createMemoryHistory())
    await router.push('/sessions')
    const wrapper = mount(AllSessionsView, { global: { plugins: [pinia, router] } })
    await flushPromises()

    const waiting = wrapper.find('[data-test="column-waiting"]')
    expect(waiting.findAll('[data-test="pending-permission"]')).toHaveLength(1)
    expect(waiting.text()).toContain('pytest -k pix')
    await waiting.find('[data-test="pending-allow"]').trigger('click')
    await flushPromises()
    expect(answers).toEqual([{ decision: 'allow_once' }])
    expect(router.currentRoute.value.fullPath).toBe('/sessions')

    useSessionsStore(pinia).applyEvent(makeEvent(
      'session.updated',
      makeSession({ session_id: 'a', title: 'Pede Bash', display_state: 'running', awaiting_decision: false, pending_permission: null }),
      1,
      'a',
    ) as never)
    await flushPromises()
    expect(wrapper.find('[data-test="column-waiting"]').text()).not.toContain('Pede Bash')
    expect(wrapper.find('[data-test="column-running"]').text()).toContain('Pede Bash')
  })
})
