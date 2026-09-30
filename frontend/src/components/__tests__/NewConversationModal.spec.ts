import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import NewConversationModal from '../NewConversationModal.vue'
import { createAppRouter } from '../../router'
import { takePendingDraft } from '../../conversation/pendingDrafts'
import { useNewConversationStore } from '../../stores/newConversation'
import { useGroupsStore } from '../../stores/groups'
import { useProjectsStore } from '../../stores/projects'
import { loadDraft } from '../../newConversationDraft'
import { jsonResponse, makeGroup, makeProject, makeSession, routeFetch } from '../../test/factories'

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

async function openModal(preset: number | null = 2, extra = {}, presetGroup?: number | null) {
  const fetch = routeFetch(handlers(extra))
  vi.stubGlobal('fetch', fetch)
  const router = createAppRouter(createMemoryHistory())
  await router.push('/inbox')
  useNewConversationStore(pinia).open(preset, presetGroup)
  const wrapper = mount(NewConversationModal, { global: { plugins: [pinia, router] }, attachTo: document.body })
  await flushPromises()
  return { wrapper, router, fetch }
}

describe('modal de nova conversa', () => {
  it('começa no projeto pedido e só lista projetos disponíveis', async () => {
    const { wrapper } = await openModal(2)
    const select = wrapper.find('[data-test="nc-project"]')
    expect((select.element as HTMLSelectElement).value).toBe('2')
    expect(select.findAll('option').map((o) => o.text())).toEqual(['a', 'b'])
  })

  it('cria a sessão, envia o prompt e abre a conversa', async () => {
    const { wrapper, router, fetch } = await openModal(2)
    await wrapper.find('[data-test="nc-prompt"]').setValue('Corrija o login')
    await wrapper.find('[data-test="nc-submit"]').trigger('click')
    await flushPromises()

    const send = fetch.mock.calls.find(([url]) => url === '/api/sessions/nova/messages')!
    expect(JSON.parse(send[1]!.body as string)).toEqual({ text: 'Corrija o login' })
    expect(fetch.mock.calls.some(([, init]) => init?.method === 'PATCH')).toBe(false)
    expect(router.currentRoute.value.fullPath).toBe('/sessions/nova')
    expect(useNewConversationStore(pinia).isOpen).toBe(false)
    expect(localStorage.getItem('vibing:new-conversation')).toBeNull()
  })

  it('envia título quando preenchido', async () => {
    const { wrapper, fetch } = await openModal(2)
    await wrapper.find('[data-test="nc-title"]').setValue('Login')
    await wrapper.find('[data-test="nc-prompt"]').setValue('Corrija')
    await wrapper.find('[data-test="nc-submit"]').trigger('click')
    await flushPromises()

    const patch = fetch.mock.calls.find(([, init]) => init?.method === 'PATCH')!
    expect(JSON.parse(patch[1]!.body as string)).toEqual({ title: 'Login' })
  })

  it('Enter inicia e Ctrl+Enter quebra linha', async () => {
    const { wrapper, fetch } = await openModal(2)
    const prompt = wrapper.find('[data-test="nc-prompt"]')
    await prompt.setValue('linha 1')
    await prompt.trigger('keydown', { key: 'Enter', ctrlKey: true })
    expect((prompt.element as HTMLTextAreaElement).value).toBe('linha 1\n')
    await prompt.trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(fetch.mock.calls.some(([url]) => url === '/api/projects/2/sessions')).toBe(true)
  })

  it('não cria duas sessões com dois envios seguidos', async () => {
    const { wrapper, fetch } = await openModal(2)
    await wrapper.find('[data-test="nc-prompt"]').setValue('oi')
    await wrapper.find('[data-test="nc-submit"]').trigger('click')
    await wrapper.find('[data-test="nc-prompt"]').trigger('keydown', { key: 'Enter' })
    await flushPromises()

    expect(fetch.mock.calls.filter(([url]) => url === '/api/projects/2/sessions')).toHaveLength(1)
  })

  it('mantém o rascunho quando a criação falha', async () => {
    const { wrapper } = await openModal(2, {
      'POST /api/projects/2/sessions': () => jsonResponse({ detail: 'Pasta indisponível.' }, 409),
    })
    await wrapper.find('[data-test="nc-prompt"]').setValue('oi')
    await wrapper.find('[data-test="nc-submit"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-test="nc-error"]').text()).toContain('Pasta indisponível.')
    expect((wrapper.find('[data-test="nc-prompt"]').element as HTMLTextAreaElement).value).toBe('oi')
    expect(useNewConversationStore(pinia).isOpen).toBe(true)
  })

  it('abre a conversa com o prompt no compositor quando o envio falha', async () => {
    const { wrapper, router } = await openModal(2, {
      'POST /api/sessions/nova/messages': () => jsonResponse({ detail: 'Sem conexão.' }, 503),
    })
    await wrapper.find('[data-test="nc-prompt"]').setValue('oi')
    await wrapper.find('[data-test="nc-submit"]').trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.fullPath).toBe('/sessions/nova')
    expect(takePendingDraft('nova')).toEqual({ text: 'oi', error: 'Sem conexão.', images: [] })
  })

  it('guarda o rascunho ao fechar e restaura ao abrir', async () => {
    const first = await openModal(2)
    await first.wrapper.find('[data-test="nc-prompt"]').setValue('rascunho')
    await first.wrapper.find('[data-test="nc-close"]').trigger('click')
    first.wrapper.unmount()

    const second = await openModal(null)
    expect((second.wrapper.find('[data-test="nc-prompt"]').element as HTMLTextAreaElement).value).toBe('rascunho')
    expect((second.wrapper.find('[data-test="nc-project"]').element as HTMLSelectElement).value).toBe('2')
  })

  it('rascunho com projeto removido cai no projeto padrão', async () => {
    localStorage.setItem('vibing:new-conversation', JSON.stringify({ projectId: 99, title: '', prompt: 'x', model: null, effort: null, permissionMode: null }))
    const { wrapper } = await openModal(null)
    expect((wrapper.find('[data-test="nc-project"]').element as HTMLSelectElement).value).toBe('1')
  })

  it('descartar limpa o rascunho', async () => {
    const { wrapper } = await openModal(2)
    await wrapper.find('[data-test="nc-prompt"]').setValue('lixo')
    await wrapper.find('[data-test="nc-discard"]').trigger('click')
    expect(localStorage.getItem('vibing:new-conversation')).toBeNull()
    expect(useNewConversationStore(pinia).isOpen).toBe(false)
  })

  it('funciona sem localStorage', async () => {
    vi.stubGlobal('localStorage', { getItem() { throw new Error('x') }, setItem() { throw new Error('x') }, removeItem() { throw new Error('x') }, clear() {} })
    const { wrapper, router } = await openModal(2)
    await wrapper.find('[data-test="nc-prompt"]').setValue('oi')
    await wrapper.find('[data-test="nc-submit"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.fullPath).toBe('/sessions/nova')
  })

  it('sem projetos pede para cadastrar um', async () => {
    useProjectsStore(pinia).projects = []
    const { wrapper } = await openModal(null)
    expect(wrapper.find('[data-test="nc-no-projects"] a').attributes('href')).toBe('/projects/new')
  })
})

describe('modal de nova conversa: revisão', () => {
  it('Esc num menu aberto fecha só o menu', async () => {
    const { wrapper } = await openModal(2)
    const trigger = wrapper.find('button[aria-label="Modelo"]')
    await trigger.trigger('click')
    await flushPromises()
    const menu = wrapper.find('[role="menu"]')
    expect(menu.exists()).toBe(true)
    await menu.trigger('keydown', { key: 'Escape' })
    await flushPromises()
    expect(wrapper.find('[role="menu"]').exists()).toBe(false)
    expect(useNewConversationStore(pinia).isOpen).toBe(true)
  })

  it('Esc fora dos menus fecha o modal', async () => {
    const { wrapper } = await openModal(2)
    await wrapper.find('[data-test="nc-prompt"]').trigger('keydown', { key: 'Escape' })
    expect(useNewConversationStore(pinia).isOpen).toBe(false)
  })

  it('devolve o foco a quem estava focado antes ao fechar', async () => {
    const opener = document.createElement('button')
    document.body.appendChild(opener)
    opener.focus()
    const { wrapper } = await openModal(2)
    expect(document.activeElement).not.toBe(opener)
    await wrapper.find('[data-test="nc-close"]').trigger('click')
    expect(document.activeElement).toBe(opener)
    opener.remove()
  })

  it('devolve o foco ao descartar', async () => {
    const opener = document.createElement('button')
    document.body.appendChild(opener)
    opener.focus()
    const { wrapper } = await openModal(2)
    await wrapper.find('[data-test="nc-discard"]').trigger('click')
    expect(document.activeElement).toBe(opener)
    opener.remove()
  })

  it('Tab no último foco volta ao primeiro e Shift+Tab no primeiro vai ao último', async () => {
    const { wrapper } = await openModal(2)
    const dialog = wrapper.find('[data-test="new-conversation-modal"]')
    const focusables = Array.from(dialog.element.querySelectorAll<HTMLElement>('button:not([disabled]), input, select, textarea, a[href]'))
    const first = focusables[0]!
    const last = focusables[focusables.length - 1]!
    // The submit button is disabled while the prompt is empty: fill it so it is the last one.
    await wrapper.find('[data-test="nc-prompt"]').setValue('oi')
    const list = Array.from(dialog.element.querySelectorAll<HTMLElement>('button:not([disabled]), input, select, textarea, a[href]'))
    expect(list[list.length - 1]).toBe(wrapper.find('[data-test="nc-submit"]').element)
    ;(list[list.length - 1] as HTMLElement).focus()
    await dialog.trigger('keydown', { key: 'Tab' })
    expect(document.activeElement).toBe(list[0])
    list[0]!.focus()
    await dialog.trigger('keydown', { key: 'Tab', shiftKey: true })
    expect(document.activeElement).toBe(list[list.length - 1])
    expect(first).toBeTruthy()
    expect(last).toBeTruthy()
  })

  it('reabre no último projeto usado depois de enviar', async () => {
    const first = await openModal(2)
    await first.wrapper.find('[data-test="nc-prompt"]').setValue('oi')
    await first.wrapper.find('[data-test="nc-submit"]').trigger('click')
    await flushPromises()
    expect(localStorage.getItem('vibing:new-conversation-last-project')).toBe('2')
    first.wrapper.unmount()

    const second = await openModal(null)
    expect((second.wrapper.find('[data-test="nc-project"]').element as HTMLSelectElement).value).toBe('2')
  })

  it('último projeto indisponível cai no primeiro disponível', async () => {
    localStorage.setItem('vibing:new-conversation-last-project', '3')
    const { wrapper } = await openModal(null)
    expect((wrapper.find('[data-test="nc-project"]').element as HTMLSelectElement).value).toBe('1')
  })

  it('Shift+Enter não envia e não bloqueia a quebra de linha', async () => {
    const { wrapper, fetch } = await openModal(2)
    const prompt = wrapper.find('[data-test="nc-prompt"]')
    await prompt.setValue('oi')
    const event = new KeyboardEvent('keydown', { key: 'Enter', shiftKey: true, cancelable: true, bubbles: true })
    prompt.element.dispatchEvent(event)
    await flushPromises()
    expect(event.defaultPrevented).toBe(false)
    expect(fetch.mock.calls.some(([url]) => url === '/api/projects/2/sessions')).toBe(false)
  })

  it('Enter durante composição de IME não envia', async () => {
    const { wrapper, fetch } = await openModal(2)
    const prompt = wrapper.find('[data-test="nc-prompt"]')
    await prompt.setValue('oi')
    await prompt.trigger('keydown', { key: 'Enter', keyCode: 229 })
    await flushPromises()
    expect(fetch.mock.calls.some(([url]) => url === '/api/projects/2/sessions')).toBe(false)
  })

  it('rascunho com valores inválidos vira nulo', async () => {
    localStorage.setItem('vibing:new-conversation', JSON.stringify({ projectId: 2, title: '', prompt: 'x', model: null, effort: 'enorme', permissionMode: 'bypassPermissions' }))
    const { wrapper, fetch } = await openModal(null)
    await wrapper.find('[data-test="nc-submit"]').trigger('click')
    await flushPromises()
    expect(fetch.mock.calls.some(([, init]) => init?.method === 'PATCH')).toBe(false)
  })
})

describe('modal de nova conversa: agrupador', () => {
  function seedGroups() {
    const groups = useGroupsStore(pinia)
    groups.groups = [makeGroup({ id: 2, project_id: 1, name: 'Checkout' }), makeGroup({ id: 5, project_id: 2, name: 'Outro' })]
    groups.loaded = true
    return groups
  }
  const groupValue = (wrapper: Awaited<ReturnType<typeof openModal>>['wrapper']) =>
    (wrapper.find('[data-test="nc-group"]').element as HTMLSelectElement).value

  const groupText = (wrapper: Awaited<ReturnType<typeof openModal>>['wrapper']) => {
    const select = wrapper.find('[data-test="nc-group"]').element as HTMLSelectElement
    return select.selectedOptions[0]?.textContent
  }

  it('começa no agrupador pedido quando ele é do projeto escolhido', async () => {
    seedGroups()
    const { wrapper } = await openModal(1, {}, 2)
    expect(groupValue(wrapper)).toBe('2')
    expect(wrapper.find('[data-test="nc-group"]').findAll('option').map((o) => o.text())).toEqual(['Nenhum', 'Checkout'])
  })

  it('ignora o agrupador pedido de outro projeto', async () => {
    seedGroups()
    const { wrapper } = await openModal(1, {}, 5)
    expect(groupText(wrapper)).toBe('Nenhum')
  })

  it('não mostra o seletor quando o projeto não tem agrupadores', async () => {
    const { wrapper } = await openModal(1, {}, null)
    expect(wrapper.find('[data-test="nc-group"]').exists()).toBe(false)
  })

  it('trocar o projeto volta o agrupador para Nenhum', async () => {
    seedGroups()
    const { wrapper } = await openModal(1, {}, 2)
    const project = wrapper.find('[data-test="nc-project"]')
    await project.setValue('2')
    await project.trigger('change')
    expect(groupText(wrapper)).toBe('Nenhum')
  })

  it('cria a sessão dentro do agrupador escolhido', async () => {
    seedGroups()
    const { wrapper, fetch } = await openModal(1, { 'POST /api/projects/1/sessions': () => jsonResponse(makeSession({ session_id: 'nova', project_id: 1 }), 201) }, 2)
    await wrapper.find('[data-test="nc-prompt"]').setValue('Corrija')
    await wrapper.find('[data-test="nc-submit"]').trigger('click')
    await flushPromises()
    const create = fetch.mock.calls.find(([url]) => url === '/api/projects/1/sessions')!
    expect(JSON.parse(create[1]!.body as string)).toEqual({ group_id: 2 })
  })

  it('o agrupador fica desabilitado depois de a sessão ser criada', async () => {
    seedGroups()
    const { wrapper } = await openModal(1, {
      'POST /api/projects/1/sessions': () => jsonResponse(makeSession({ session_id: 'nova', project_id: 1 }), 201),
      'PATCH /api/sessions/nova': () => jsonResponse({ detail: 'falhou' }, 500),
    }, 2)
    await wrapper.find('[data-test="nc-title"]').setValue('T')
    await wrapper.find('[data-test="nc-prompt"]').setValue('Corrija')
    await wrapper.find('[data-test="nc-submit"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-test="nc-group"]').attributes('disabled')).toBeDefined()
  })

  it('volta para Nenhum quando o agrupador escolhido é removido com o modal aberto', async () => {
    const groups = seedGroups()
    groups.groups.push(makeGroup({ id: 6, project_id: 1, name: 'Restante' }))
    const { wrapper } = await openModal(1, {}, 2)
    expect(groupValue(wrapper)).toBe('2')
    groups.groups = groups.groups.filter((g) => g.id !== 2)
    await flushPromises()
    expect(groupText(wrapper)).toBe('Nenhum')
    expect(JSON.parse(localStorage.getItem('vibing:new-conversation')!).groupId).toBeNull()
  })

  it('aberto antes de os agrupadores carregarem, guarda o pedido e o aplica quando chegam', async () => {
    const groups = useGroupsStore(pinia)
    groups.loaded = false
    const { wrapper } = await openModal(1, {}, 2)
    // The draft was not wiped while the groups were unknown.
    expect(JSON.parse(localStorage.getItem('vibing:new-conversation')!).groupId).toBe(2)

    groups.groups = [makeGroup({ id: 2, project_id: 1, name: 'Checkout' })]
    groups.loaded = true
    await flushPromises()
    expect(groupValue(wrapper)).toBe('2')
  })

  it('aberto antes da carga, o agrupador do rascunho também volta quando os agrupadores chegam', async () => {
    localStorage.setItem('vibing:new-conversation', JSON.stringify({ projectId: 1, groupId: 2, title: '', prompt: 'x', model: null, effort: null, permissionMode: null }))
    const groups = useGroupsStore(pinia)
    groups.loaded = false
    const { wrapper } = await openModal(null)
    groups.groups = [makeGroup({ id: 2, project_id: 1, name: 'Checkout' })]
    groups.loaded = true
    await flushPromises()
    expect(groupValue(wrapper)).toBe('2')
  })

  it('aberto de uma conversa sem agrupador (null), mostra Nenhum mesmo com rascunho', async () => {
    seedGroups()
    localStorage.setItem('vibing:new-conversation', JSON.stringify({ projectId: 1, groupId: 2, title: '', prompt: 'x', model: null, effort: null, permissionMode: null }))
    const { wrapper } = await openModal(1, {}, null)
    expect(groupText(wrapper)).toBe('Nenhum')
  })

  it('aberto sem preferência de agrupador (undefined), vale o rascunho', async () => {
    seedGroups()
    localStorage.setItem('vibing:new-conversation', JSON.stringify({ projectId: 1, groupId: 2, title: '', prompt: 'x', model: null, effort: null, permissionMode: null }))
    const { wrapper } = await openModal(1)
    expect(groupValue(wrapper)).toBe('2')
  })

  it('guarda o agrupador no rascunho e o restaura ao abrir', async () => {
    seedGroups()
    localStorage.setItem('vibing:new-conversation', JSON.stringify({ projectId: 1, groupId: 2, title: '', prompt: 'x', model: null, effort: null, permissionMode: null }))
    const { wrapper } = await openModal(null)
    expect(groupValue(wrapper)).toBe('2')
  })

  it('loadDraft aceita só número como agrupador', () => {
    localStorage.setItem('vibing:new-conversation', JSON.stringify({ groupId: 'x' }))
    expect(loadDraft().groupId).toBeNull()
    localStorage.setItem('vibing:new-conversation', JSON.stringify({ groupId: 3 }))
    expect(loadDraft().groupId).toBe(3)
    localStorage.clear()
    expect(loadDraft().groupId).toBeNull()
  })
})
