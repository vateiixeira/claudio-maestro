import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory, type Router } from 'vue-router'
import ProjectView from '../ProjectView.vue'
import { createAppRouter } from '../../router'
import { jsonResponse, makeProject, makeSession, routeFetch } from '../../test/factories'
import { useProjectsStore } from '../../stores/projects'

enableAutoUnmount(afterEach)

let pinia: Pinia
let router: Router

beforeEach(async () => {
  pinia = createPinia()
  setActivePinia(pinia)
  router = createAppRouter(createMemoryHistory())
  await router.push('/projects/1')
})

afterEach(() => vi.unstubAllGlobals())

function seed(available = true) {
  const projects = useProjectsStore(pinia)
  projects.projects = [makeProject({ id: 1, name: 'loja-online', available })]
  projects.loaded = true
}

async function mountView() {
  const wrapper = mount(ProjectView, { props: { id: 1 }, global: { plugins: [pinia, router] } })
  await flushPromises()
  return wrapper
}

describe('tela do projeto', () => {
  it('mostra nome, caminho e sessões', async () => {
    seed()
    vi.stubGlobal(
      'fetch',
      routeFetch({
        'GET /api/projects/1/sessions': () =>
          jsonResponse([makeSession({ session_id: 'a', title: 'Cupom expirado', state: 'idle' })]),
      }),
    )
    const wrapper = await mountView()

    expect(wrapper.find('h1').text()).toBe('loja-online')
    expect(wrapper.text()).toContain('/home/vi/dev/loja-online')
    const rows = wrapper.findAll('[data-test="session-row"]')
    expect(rows).toHaveLength(1)
    expect(rows[0]!.text()).toContain('Cupom expirado')
    expect(rows[0]!.text()).toContain('Aguardando você')
    expect(rows[0]!.attributes('href')).toBe('/sessions/a')
  })

  it('"Nova sessão" cria a sessão e navega para ela', async () => {
    seed()
    const fetchMock = routeFetch({
      'GET /api/projects/1/sessions': () => jsonResponse([]),
      'POST /api/projects/1/sessions': () => jsonResponse(makeSession({ session_id: 'nova' }), 201),
    })
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = await mountView()

    await wrapper.find('[data-test="new-session"]').trigger('click')
    await flushPromises()

    expect(fetchMock).toHaveBeenCalledWith('/api/projects/1/sessions', expect.objectContaining({ method: 'POST' }))
    expect(router.currentRoute.value.fullPath).toBe('/sessions/nova')
  })

  it('mostra o erro ao criar sessão', async () => {
    seed()
    vi.stubGlobal(
      'fetch',
      routeFetch({
        'GET /api/projects/1/sessions': () => jsonResponse([]),
        'POST /api/projects/1/sessions': () => jsonResponse({ detail: 'A pasta do projeto não existe.' }, 409),
      }),
    )
    const wrapper = await mountView()
    await wrapper.find('[data-test="new-session"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[role="alert"]').text()).toContain('A pasta do projeto não existe.')
    expect(router.currentRoute.value.fullPath).toBe('/projects/1')
  })

  it('desabilita "Nova sessão" com explicação quando a pasta está indisponível', async () => {
    seed(false)
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/projects/1/sessions': () => jsonResponse([]) }))
    const wrapper = await mountView()

    const button = wrapper.find('[data-test="new-session"]')
    expect(button.attributes('disabled')).toBeDefined()
    const hintId = button.attributes('aria-describedby')!
    expect(wrapper.find(`#${hintId}`).text()).toContain('não existe mais')
  })

  it('remover pede confirmação e explica que a pasta e as conversas ficam', async () => {
    seed()
    const fetchMock = routeFetch({
      'GET /api/projects/1/sessions': () => jsonResponse([]),
      'DELETE /api/projects/1': () => new Response(null, { status: 204 }),
    })
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = await mountView()

    await wrapper.find('[data-test="remove"]').trigger('click')
    const dialog = wrapper.find('[data-test="confirm-remove"]')
    expect(dialog.exists()).toBe(true)
    expect(dialog.text()).toContain('A pasta e as conversas não são apagadas')
    expect(fetchMock).not.toHaveBeenCalledWith('/api/projects/1', expect.objectContaining({ method: 'DELETE' }))

    await dialog.find('[data-test="confirm-remove-cancel"]').trigger('click')
    expect(wrapper.find('[data-test="confirm-remove"]').exists()).toBe(false)

    await wrapper.find('[data-test="remove"]').trigger('click')
    await wrapper.find('[data-test="confirm-remove-ok"]').trigger('click')
    await flushPromises()

    expect(fetchMock).toHaveBeenCalledWith('/api/projects/1', expect.objectContaining({ method: 'DELETE' }))
    expect(useProjectsStore(pinia).projects).toEqual([])
    expect(router.currentRoute.value.fullPath).toBe('/')
  })

  it('renomeia o projeto', async () => {
    seed()
    vi.stubGlobal(
      'fetch',
      routeFetch({
        'GET /api/projects/1/sessions': () => jsonResponse([]),
        'PATCH /api/projects/1': (init) =>
          jsonResponse(makeProject({ id: 1, name: JSON.parse(init!.body as string).name })),
      }),
    )
    const wrapper = await mountView()

    await wrapper.find('[data-test="rename"]').trigger('click')
    await wrapper.find('#rename-project').setValue('loja-nova')
    await wrapper.find('[data-test="rename-form"]').trigger('submit')
    await flushPromises()

    expect(wrapper.find('h1').text()).toBe('loja-nova')
    expect(useProjectsStore(pinia).byId(1)?.name).toBe('loja-nova')
  })

  it('avisa quando o projeto não existe', async () => {
    const projects = useProjectsStore(pinia)
    projects.loaded = true
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/projects/1/sessions': () => jsonResponse({ detail: 'Projeto não encontrado.' }, 404) }))
    const wrapper = await mountView()
    expect(wrapper.text()).toContain('Projeto não encontrado')
  })

  it('Atualizar sincroniza o projeto com o histórico', async () => {
    seed()
    const sync = vi.fn(() => jsonResponse([makeSession({ session_id: 'nova', title: 'Veio do CLI' })]))
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/projects/1/sessions': () => jsonResponse([]),
      'POST /api/projects/1/sync': sync,
    }))
    const wrapper = await mountView()
    await wrapper.find('[data-test="sync"]').trigger('click')
    await flushPromises()
    expect(sync).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('Veio do CLI')
  })

  it('Atualizar recarrega também a lista de projetos', async () => {
    seed()
    const list = vi.fn(() => jsonResponse([makeProject({ id: 1, name: 'loja-online', hidden_sessions: 2 })]))
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/projects/1/sessions': () => jsonResponse([]),
      'POST /api/projects/1/sync': () => jsonResponse([]),
      'GET /api/projects': list,
    }))
    const wrapper = await mountView()
    await wrapper.find('[data-test="sync"]').trigger('click')
    await flushPromises()
    expect(list).toHaveBeenCalledTimes(1)
    expect(useProjectsStore(pinia).byId(1)?.hidden_sessions).toBe(2)
  })

  it('rola até Finalizadas quando chega com #finalizadas, depois de carregar', async () => {
    seed()
    const scroll = vi.fn()
    Element.prototype.scrollIntoView = scroll
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/projects/1/sessions': () => jsonResponse([makeSession({ display_state: 'finished', finished: true })]),
    }))
    await router.push('/projects/1#finalizadas')
    const wrapper = mount(ProjectView, { props: { id: 1 }, attachTo: document.body, global: { plugins: [pinia, router] } })
    await flushPromises()
    expect(scroll).toHaveBeenCalledTimes(1)
    expect((scroll.mock.contexts[0] as HTMLElement).id).toBe('finalizadas')
    wrapper.unmount()
  })
})
