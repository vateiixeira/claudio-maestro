import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import NewConversationModal from '../NewConversationModal.vue'
import { createAppRouter } from '../../router'
import { useNewConversationStore } from '../../stores/newConversation'
import { useProjectsStore } from '../../stores/projects'
import { FakeRecognition } from '../../test/fakeRecognition'
import { jsonResponse, makeProject, makeSession, routeFetch } from '../../test/factories'

enableAutoUnmount(afterEach)
let pinia: Pinia

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  localStorage.clear()
  const projects = useProjectsStore(pinia)
  projects.projects = [
    makeProject({ id: 1, name: 'a' }),
    makeProject({ id: 2, name: 'b', path: '/b' }),
    makeProject({ id: 3, name: 'sumiu', path: '/c', available: false }),
  ]
  projects.loaded = true
})
afterEach(() => vi.unstubAllGlobals())

function handlers(extra = {}) {
  return {
    'GET /api/models': () => jsonResponse([]),
    'POST /api/projects/2/sessions': () => jsonResponse(makeSession({ session_id: 'nova', project_id: 2 }), 201),
    'POST /api/sessions/nova/messages': () => jsonResponse({ state: 'running', external_activity: false }, 202),
    'PATCH /api/sessions/nova': () => jsonResponse(makeSession({ session_id: 'nova', project_id: 2 })),
    ...extra,
  }
}

async function openModal(preset: number | null = 2, extra = {}) {
  const fetch = routeFetch(handlers(extra))
  vi.stubGlobal('fetch', fetch)
  const router = createAppRouter(createMemoryHistory())
  await router.push('/inbox')
  useNewConversationStore(pinia).open(preset)
  const wrapper = mount(NewConversationModal, { global: { plugins: [pinia, router] }, attachTo: document.body })
  await flushPromises()
  return { wrapper, router, fetch }
}

describe('modal de nova conversa: ditado', () => {
  it('sem suporte do navegador, o botão não aparece', async () => {
    const { wrapper } = await openModal(2)
    expect(wrapper.find('[data-test="nc-dictate"]').exists()).toBe(false)
  })

  it('dita no cursor do prompt e não envia sozinho', async () => {
    vi.stubGlobal('webkitSpeechRecognition', FakeRecognition)
    const { wrapper, fetch } = await openModal(2)
    const prompt = wrapper.find('[data-test="nc-prompt"]')
    await prompt.setValue('corrija bug')
    ;(prompt.element as HTMLTextAreaElement).setSelectionRange(8, 8)
    const mic = wrapper.find('[data-test="nc-dictate"]')
    expect(mic.attributes('aria-label')).toBe('Ditar mensagem')
    await mic.trigger('click')
    const rec = FakeRecognition.last!
    expect(rec.lang).toBe('pt-BR')
    expect(wrapper.find('[data-test="nc-recording"]').text()).toContain('Gravando')
    rec.emit(['o', true])
    await flushPromises()
    expect((prompt.element as HTMLTextAreaElement).value).toBe('corrija o bug')
    expect(fetch.mock.calls.filter(([url]) => String(url).includes('/sessions')).length).toBe(0)
  })

  it('iniciar a conversa para o ditado', async () => {
    vi.stubGlobal('webkitSpeechRecognition', FakeRecognition)
    const { wrapper } = await openModal(2)
    await wrapper.find('[data-test="nc-dictate"]').trigger('click')
    const rec = FakeRecognition.last!
    rec.emit(['oi', true])
    await flushPromises()
    await wrapper.find('[data-test="nc-submit"]').trigger('click')
    await flushPromises()
    expect(rec.started).toBe(false)
  })

  it('fechar o modal para o ditado', async () => {
    vi.stubGlobal('webkitSpeechRecognition', FakeRecognition)
    const { wrapper } = await openModal(2)
    await wrapper.find('[data-test="nc-dictate"]').trigger('click')
    const rec = FakeRecognition.last!
    await wrapper.find('[data-test="nc-prompt"]').trigger('keydown', { key: 'Escape' })
    await flushPromises()
    expect(rec.started).toBe(false)
  })

  it('digitar durante a gravação para o ditado', async () => {
    vi.stubGlobal('webkitSpeechRecognition', FakeRecognition)
    const { wrapper } = await openModal(2)
    await wrapper.find('[data-test="nc-dictate"]').trigger('click')
    await wrapper.find('[data-test="nc-prompt"]').setValue('escrevi')
    expect(wrapper.find('[data-test="nc-dictate"]').attributes('aria-pressed')).toBe('false')
  })
})
