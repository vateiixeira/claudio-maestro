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

describe('modal de nova conversa: comandos e menções', () => {
  async function typeSlash(wrapper: Awaited<ReturnType<typeof openModal>>['wrapper'], value: string) {
    const ta = wrapper.get('[data-test="nc-prompt"]')
    await ta.setValue(value)
    ;(ta.element as HTMLTextAreaElement).setSelectionRange(value.length, value.length)
    await ta.trigger('input')
    await flushPromises()
    return ta
  }

  it('usa os comandos do projeto escolhido', async () => {
    const { wrapper, fetch } = await openModal(2, {
      'GET /api/projects/2/commands': () => jsonResponse([{ name: 'commit', description: '', argument_hint: '' }]),
    })
    await typeSlash(wrapper, '/co')
    expect(wrapper.find('[role="listbox"]').text()).toContain('/commit')
    expect(fetch.mock.calls.some((c) => c[0] === '/api/projects/2/commands')).toBe(true)
  })

  it('trocar de projeto zera a lista e fecha o menu', async () => {
    const { wrapper, fetch } = await openModal(2, {
      'GET /api/projects/2/commands': () => jsonResponse([{ name: 'commit', description: '', argument_hint: '' }]),
      'GET /api/projects/1/commands': () => jsonResponse([{ name: 'hello', description: '', argument_hint: '' }]),
    })
    const ta = await typeSlash(wrapper, '/')
    await wrapper.get('[data-test="nc-project"]').setValue(1)
    await flushPromises()
    expect(wrapper.find('[role="listbox"]').exists()).toBe(false)
    await ta.trigger('input')
    await flushPromises()
    expect(wrapper.get('[role="listbox"]').text()).toContain('/hello')
    expect(fetch.mock.calls.filter((c) => String(c[0]).endsWith('/commands'))).toHaveLength(2)
  })

  it('Esc fecha só o menu, não o modal', async () => {
    const { wrapper } = await openModal(2, {
      'GET /api/projects/2/commands': () => jsonResponse([{ name: 'commit', description: '', argument_hint: '' }]),
    })
    const ta = await typeSlash(wrapper, '/co')
    await ta.trigger('keydown', { key: 'Escape' })
    expect(wrapper.find('[role="listbox"]').exists()).toBe(false)
    expect(useNewConversationStore(pinia).isOpen).toBe(true)
  })

  it('Enter com menu aberto escolhe e não cria a conversa', async () => {
    const { wrapper, fetch } = await openModal(2, {
      'GET /api/projects/2/commands': () => jsonResponse([{ name: 'commit', description: '', argument_hint: '' }]),
    })
    const ta = await typeSlash(wrapper, '/co')
    await ta.trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect((ta.element as HTMLTextAreaElement).value).toBe('/commit ')
    expect(fetch.mock.calls.some((c) => c[0] === '/api/projects/2/sessions')).toBe(false)
  })

  it('o campo expõe os atributos de combobox', async () => {
    const { wrapper } = await openModal(2, {
      'GET /api/projects/2/commands': () => jsonResponse([{ name: 'commit', description: '', argument_hint: '' }]),
    })
    const ta = await typeSlash(wrapper, '/co')
    expect(ta.attributes('role')).toBe('combobox')
    expect(ta.attributes('aria-expanded')).toBe('true')
    expect(ta.attributes('aria-controls')).toBe(wrapper.get('[role="listbox"]').attributes('id'))
  })

  it('o ditado fecha o menu e não o reabre ao posicionar o cursor', async () => {
    vi.stubGlobal('webkitSpeechRecognition', FakeRecognition)
    const { wrapper } = await openModal(2, {
      'GET /api/projects/2/commands': () => jsonResponse([{ name: 'commit', description: '', argument_hint: '' }]),
    })
    const ta = await typeSlash(wrapper, '/co')
    expect(wrapper.find('[role="listbox"]').exists()).toBe(true)
    await wrapper.get('[data-test="nc-dictate"]').trigger('click')
    expect(wrapper.find('[role="listbox"]').exists()).toBe(false)
    FakeRecognition.last!.emit([' mais', true])
    await flushPromises()
    await ta.trigger('select')
    expect(wrapper.find('[role="listbox"]').exists()).toBe(false)
  })

  it('enviar fecha o menu', async () => {
    const { wrapper } = await openModal(2, {
      'GET /api/projects/2/commands': () => jsonResponse([{ name: 'commit', description: '', argument_hint: '' }]),
    })
    await typeSlash(wrapper, '/co')
    await wrapper.get('[data-test="nc-submit"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[role="listbox"]').exists()).toBe(false)
  })

  it('sem espaço medido (jsdom), o menu abre abaixo do campo', async () => {
    const { wrapper } = await openModal(2, {
      'GET /api/projects/2/commands': () => jsonResponse([{ name: 'commit', description: '', argument_hint: '' }]),
    })
    await typeSlash(wrapper, '/co')
    expect(wrapper.get('[role="listbox"]').classes()).toContain('top-full')
  })

  it('com 288 px ou mais acima do campo no corpo rolável, o menu abre acima', async () => {
    const { wrapper } = await openModal(2, {
      'GET /api/projects/2/commands': () => jsonResponse([{ name: 'commit', description: '', argument_hint: '' }]),
    })
    const ta = wrapper.get('[data-test="nc-prompt"]')
    vi.spyOn(ta.element, 'getBoundingClientRect').mockReturnValue({ top: 400 } as DOMRect)
    await typeSlash(wrapper, '/co')
    expect(wrapper.get('[role="listbox"]').classes()).toContain('bottom-full')
  })
})
