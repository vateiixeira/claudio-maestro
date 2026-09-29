import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import ConversationRow from '../ConversationRow.vue'
import { createAppRouter } from '../../../router'
import { useGitStore } from '../../../stores/git'
import { useProjectsStore } from '../../../stores/projects'
import { jsonResponse, makeGitRepo, makeProject, makeSession, routeFetch } from '../../../test/factories'

enableAutoUnmount(afterEach)
let pinia: Pinia

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  const projects = useProjectsStore(pinia)
  projects.projects = [makeProject({ id: 1, name: 'loja-online', color: '#B28CFF' })]
  projects.loaded = true
  useGitStore(pinia).set(1, [makeGitRepo({ branch: 'develop' })])
})
afterEach(() => vi.unstubAllGlobals())

function mountRow(session = makeSession(), variant?: 'inbox' | 'list' | 'compact') {
  const router = createAppRouter(createMemoryHistory())
  return mount(ConversationRow, { props: { session, variant }, global: { plugins: [pinia, router] } })
}

describe('linha de conversa', () => {
  it('mostra título, projeto, branch e tempo, e abre a conversa', () => {
    const wrapper = mountRow(makeSession({ session_id: 'abc', title: 'Corrigir login' }))

    expect(wrapper.find('[data-test="row-link"]').text()).toBe('Corrigir login')
    expect(wrapper.find('[data-test="row-link"]').attributes('href')).toBe('/sessions/abc')
    expect(wrapper.find('[data-test="row-project"]').text()).toContain('loja-online')
    expect(wrapper.find('[data-test="row-branch"]').text()).toContain('develop')
  })

  it('mostra a bolinha de não lida e o motivo da espera', () => {
    const wrapper = mountRow(makeSession({ unread: true, display_state: 'waiting', state: 'awaiting_decision', pending_kind: 'question' }))

    expect(wrapper.find('[data-test="unread-dot"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="waiting-reason"]').text()).toBe('Fez uma pergunta')
  })

  it('apaga o texto de finalizadas e oferece Reabrir', () => {
    const wrapper = mountRow(makeSession({ display_state: 'finished', finished: true }))

    expect(wrapper.find('[data-test="row-link"]').classes()).toContain('text-fg-muted')
    expect(wrapper.find('[data-test="row-reopen"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="row-finish"]').exists()).toBe(false)
  })

  it('finaliza pela ação da linha', async () => {
    const fetch = routeFetch({
      'PATCH /api/sessions/s1': () => jsonResponse(makeSession({ display_state: 'finished', finished: true })),
    })
    vi.stubGlobal('fetch', fetch)
    const wrapper = mountRow(makeSession({ display_state: 'waiting' }))

    await wrapper.find('[data-test="row-finish"]').trigger('click')
    await flushPromises()

    expect(JSON.parse(fetch.mock.calls[0]![1]!.body as string)).toEqual({ finished: true })
  })

  it('marca como lida só na Inbox', async () => {
    const fetch = routeFetch({ 'POST /api/sessions/s1/seen': () => jsonResponse(makeSession()) })
    vi.stubGlobal('fetch', fetch)

    expect(mountRow(makeSession({ unread: true }), 'list').find('[data-test="row-mark-read"]').exists()).toBe(false)
    const inbox = mountRow(makeSession({ unread: true }), 'inbox')
    await inbox.find('[data-test="row-mark-read"]').trigger('click')
    await flushPromises()

    expect(fetch).toHaveBeenCalledOnce()
  })

  it('a variante compacta não tem ações', () => {
    const wrapper = mountRow(makeSession({ unread: true }), 'compact')
    expect(wrapper.find('[data-test="row-finish"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="row-mark-read"]').exists()).toBe(false)
  })

  it('avisa o erro de uma ação', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'PATCH /api/sessions/s1': () => jsonResponse({ detail: 'Falhou.' }, 500) }))
    const wrapper = mountRow(makeSession({ display_state: 'waiting' }))

    await wrapper.find('[data-test="row-finish"]').trigger('click')
    await flushPromises()

    expect(wrapper.emitted('error')).toEqual([['Falhou.']])
  })
})
