import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import InboxView from '../InboxView.vue'
import { createAppRouter } from '../../router'
import { useProjectsStore } from '../../stores/projects'
import { useSessionsStore } from '../../stores/sessions'
import { jsonResponse, makeProject, makeSession, routeFetch } from '../../test/factories'

vi.mock('../../stores/realtime', () => ({ loadEverything: vi.fn(() => Promise.resolve()) }))
import { loadEverything } from '../../stores/realtime'

enableAutoUnmount(afterEach)
let pinia: Pinia
const now = Date.now() / 1000

beforeEach(() => {
  vi.mocked(loadEverything).mockClear()
  pinia = createPinia()
  setActivePinia(pinia)
  const projects = useProjectsStore(pinia)
  projects.projects = [makeProject({ id: 1, name: 'a' }), makeProject({ id: 2, name: 'b', path: '/b' })]
  projects.loaded = true
  useSessionsStore(pinia).loaded = true
  useSessionsStore(pinia).setForProject(1, [
    makeSession({ session_id: 'w1', title: 'Espera 1', display_state: 'waiting', last_activity_at: now }),
    makeSession({ session_id: 'r1', title: 'Roda 1', display_state: 'running', unread: true, last_activity_at: now }),
  ])
  useSessionsStore(pinia).setForProject(2, [
    makeSession({ session_id: 'w2', project_id: 2, title: 'Espera 2', display_state: 'waiting', unread: true, last_activity_at: now - 3 * 86400 }),
    makeSession({ session_id: 'f2', project_id: 2, title: 'Feita', display_state: 'finished', unread: true, last_activity_at: now }),
  ])
  vi.stubGlobal('fetch', routeFetch({
    'GET /api/projects/1/git': () => jsonResponse({ repos: [] }),
    'GET /api/projects/2/git': () => jsonResponse({ repos: [] }),
  }))
})
afterEach(() => vi.unstubAllGlobals())

async function mountInbox(path = '/inbox') {
  const router = createAppRouter(createMemoryHistory())
  await router.push(path)
  const wrapper = mount(InboxView, { global: { plugins: [pinia, router] } })
  await flushPromises()
  return { wrapper, router }
}
const titles = (w: Awaited<ReturnType<typeof mountInbox>>['wrapper']) =>
  w.findAll('[data-test="row-link"]').map((r) => r.text())

describe('Inbox', () => {
  it('abre na aba Pede você, agrupada por data', async () => {
    const { wrapper } = await mountInbox()
    expect(titles(wrapper)).toEqual(['Espera 1', 'Espera 2'])
    expect(wrapper.findAll('[data-test="date-group"]').map((g) => g.text())).toEqual(['Hoje', 'Antes'])
  })

  it('troca de aba pela URL', async () => {
    const { wrapper, router } = await mountInbox()
    await wrapper.findAll('[data-test="inbox-tab"]')[2]!.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.query.aba).toBe('em-execucao')
    expect(titles(wrapper)).toEqual(['Roda 1'])
  })

  it('filtra por projeto e por texto', async () => {
    const { wrapper } = await mountInbox('/inbox?aba=todas')
    await wrapper.find('[data-test="inbox-project"]').setValue('2')
    expect(titles(wrapper)).toEqual(['Espera 2'])
    await wrapper.find('[data-test="inbox-project"]').setValue('')
    await wrapper.find('[data-test="inbox-search"]').setValue('roda')
    expect(titles(wrapper)).toEqual(['Roda 1'])
  })

  it('marca como lidas as conversas da aba filtrada', async () => {
    const fetch = routeFetch({
      'GET /api/projects/1/git': () => jsonResponse({ repos: [] }),
      'GET /api/projects/2/git': () => jsonResponse({ repos: [] }),
      'POST /api/sessions/seen': () => jsonResponse({ updated: 2 }),
    })
    vi.stubGlobal('fetch', fetch)
    const { wrapper } = await mountInbox('/inbox?aba=nao-lidas')

    await wrapper.find('[data-test="mark-all-read"]').trigger('click')
    await flushPromises()

    const call = fetch.mock.calls.find(([url]) => url === '/api/sessions/seen')!
    expect(JSON.parse(call[1]!.body as string)).toEqual({ session_ids: ['r1', 'w2'] })
  })

  it('mostra o erro de marcar todas sem mudar a lista', async () => {
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/projects/1/git': () => jsonResponse({ repos: [] }),
      'GET /api/projects/2/git': () => jsonResponse({ repos: [] }),
      'POST /api/sessions/seen': () => jsonResponse({ detail: 'Falhou.' }, 500),
    }))
    const { wrapper } = await mountInbox('/inbox?aba=nao-lidas')
    await wrapper.find('[data-test="mark-all-read"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-test="inbox-error"]').text()).toContain('Falhou.')
    expect(titles(wrapper)).toEqual(['Roda 1', 'Espera 2'])
  })

  it('mostra o estado vazio de cada aba', async () => {
    useSessionsStore(pinia).setForProject(1, [])
    useSessionsStore(pinia).setForProject(2, [])
    const { wrapper } = await mountInbox()
    expect(wrapper.find('[data-test="empty"]').text()).toBe('Nada pedindo você agora.')
  })

  it('sem projetos mostra os primeiros passos', async () => {
    useProjectsStore(pinia).projects = []
    const { wrapper } = await mountInbox()
    expect(wrapper.find('[data-test="first-steps"]').exists()).toBe(true)
  })

  it('enquanto as conversas carregam mostra "Carregando…" e não o aviso de vazio', async () => {
    useSessionsStore(pinia).loaded = false
    useSessionsStore(pinia).setForProject(1, [])
    useSessionsStore(pinia).setForProject(2, [])
    const { wrapper } = await mountInbox()
    expect(wrapper.find('[data-test="load-loading"]').text()).toBe('Carregando…')
    expect(wrapper.find('[data-test="empty"]').exists()).toBe(false)
  })

  it('se os projetos falharam mostra o erro com "Tentar de novo", que recarrega tudo', async () => {
    useSessionsStore(pinia).loaded = false
    useSessionsStore(pinia).setForProject(1, [])
    useSessionsStore(pinia).setForProject(2, [])
    useProjectsStore(pinia).loadError = 'Servidor caiu.'
    const { wrapper } = await mountInbox()
    expect(wrapper.find('[data-test="load-error"]').text()).toContain('Servidor caiu.')
    expect(wrapper.find('[data-test="empty"]').exists()).toBe(false)
    await wrapper.find('[data-test="load-retry"]').trigger('click')
    expect(loadEverything).toHaveBeenCalledTimes(1)
  })
})
