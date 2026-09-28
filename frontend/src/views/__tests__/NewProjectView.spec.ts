import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory, type Router } from 'vue-router'
import NewProjectView from '../NewProjectView.vue'
import { createAppRouter } from '../../router'
import { jsonResponse, makeProject, routeFetch } from '../../test/factories'
import { useProjectsStore } from '../../stores/projects'

const home = {
  path: '/home/vi',
  parent: null,
  entries: [
    { name: 'dev', path: '/home/vi/dev', git: false },
    { name: 'notas', path: '/home/vi/notas', git: false },
  ],
}
const dev = {
  path: '/home/vi/dev',
  parent: '/home/vi',
  entries: [
    { name: 'blog', path: '/home/vi/dev/blog', git: false },
    { name: 'loja-online', path: '/home/vi/dev/loja-online', git: true },
  ],
}
const dirs = {
  'GET /api/fs/dirs': () => jsonResponse(home),
  'GET /api/fs/dirs?path=%2Fhome%2Fvi': () => jsonResponse(home),
  'GET /api/fs/dirs?path=%2Fhome%2Fvi%2Fdev': () => jsonResponse(dev),
}

enableAutoUnmount(afterEach)

let pinia: Pinia
let router: Router

beforeEach(async () => {
  pinia = createPinia()
  setActivePinia(pinia)
  router = createAppRouter(createMemoryHistory())
  await router.push('/projects/new')
})

afterEach(() => vi.unstubAllGlobals())

async function mountView() {
  const wrapper = mount(NewProjectView, { global: { plugins: [pinia, router] }, attachTo: document.body })
  await flushPromises()
  return wrapper
}

function entry(wrapper: Awaited<ReturnType<typeof mountView>>, name: string) {
  const found = wrapper.findAll('[data-test="dir"]').find((d) => d.find('[data-test="dir-name"]').text() === name)
  if (!found) throw new Error(`pasta ${name} não está na lista`)
  return found
}

describe('tela de novo projeto', () => {
  it('lista a pasta pessoal e navega entre pastas', async () => {
    vi.stubGlobal('fetch', routeFetch(dirs))
    const wrapper = await mountView()

    expect(wrapper.findAll('[data-test="dir-name"]').map((d) => d.text())).toEqual(['dev', 'notas'])
    expect(wrapper.findAll('[data-test="crumb"]').map((c) => c.text())).toEqual(['~'])

    await entry(wrapper, 'dev').trigger('dblclick')
    await flushPromises()

    expect(wrapper.findAll('[data-test="dir-name"]').map((d) => d.text())).toEqual(['blog', 'loja-online'])
    expect(wrapper.findAll('[data-test="crumb"]').map((c) => c.text())).toEqual(['~', 'dev'])
    expect(entry(wrapper, 'loja-online').text()).toContain('git')
    expect(entry(wrapper, 'blog').text()).not.toContain('git')

    await wrapper.findAll('[data-test="crumb"]')[0]!.trigger('click')
    await flushPromises()
    expect(wrapper.findAll('[data-test="dir-name"]').map((d) => d.text())).toEqual(['dev', 'notas'])

    await wrapper.find('[data-test="dir-list"]').find('[data-test="dir"]').trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(wrapper.findAll('[data-test="crumb"]').map((c) => c.text())).toEqual(['~', 'dev'])

    await wrapper.find('[data-test="dir-up"]').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('[data-test="crumb"]').map((c) => c.text())).toEqual(['~'])
  })

  it('selecionar uma pasta preenche o nome, que continua editável', async () => {
    vi.stubGlobal('fetch', routeFetch(dirs))
    const wrapper = await mountView()
    const create = wrapper.find('[data-test="create"]')
    expect(create.attributes('disabled')).toBeDefined()

    // Entering a folder also selects it.
    await entry(wrapper, 'dev').trigger('dblclick')
    await flushPromises()
    expect(wrapper.find<HTMLInputElement>('#project-name').element.value).toBe('dev')

    await entry(wrapper, 'loja-online').trigger('click')
    const name = wrapper.find<HTMLInputElement>('#project-name')
    expect(name.element.value).toBe('loja-online')
    expect(entry(wrapper, 'loja-online').attributes('aria-pressed')).toBe('true')
    expect(wrapper.find('[data-test="selected-path"]').text()).toBe('~/dev/loja-online')
    expect(create.attributes('disabled')).toBeUndefined()

    await name.setValue('Loja')
    expect(name.element.value).toBe('Loja')
  })

  it('cria o projeto e vai para a tela dele', async () => {
    const created = makeProject({ id: 5, name: 'Loja', path: '/home/vi/dev/loja-online', color: '#4FD1C5' })
    const fetchMock = routeFetch({
      ...dirs,
      'POST /api/projects': () => jsonResponse(created, 201),
    })
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = await mountView()
    await entry(wrapper, 'dev').trigger('dblclick')
    await flushPromises()
    await entry(wrapper, 'loja-online').trigger('click')
    await wrapper.find('#project-name').setValue('Loja')
    await wrapper.find('[aria-label="Turquesa"]').trigger('click')

    await wrapper.find('form').trigger('submit')
    await flushPromises()

    const post = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST')!
    expect(JSON.parse(post[1]!.body as string)).toEqual({
      name: 'Loja',
      path: '/home/vi/dev/loja-online',
      color: '#4FD1C5',
    })
    expect(router.currentRoute.value.fullPath).toBe('/projects/5')
    expect(useProjectsStore(pinia).byId(5)?.name).toBe('Loja')
  })

  it('mostra o detail do erro 409 e fica na tela', async () => {
    vi.stubGlobal(
      'fetch',
      routeFetch({
        ...dirs,
        'POST /api/projects': () => jsonResponse({ detail: 'Esta pasta já é usada pelo projeto loja.' }, 409),
      }),
    )
    const wrapper = await mountView()
    await entry(wrapper, 'notas').trigger('click')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(wrapper.find('[role="alert"]').text()).toContain('Esta pasta já é usada pelo projeto loja.')
    expect(router.currentRoute.value.fullPath).toBe('/projects/new')
  })

  it('mostra o erro do navegador de pastas', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/fs/dirs': () => jsonResponse({ detail: 'Sem acesso.' }, 403) }))
    const wrapper = await mountView()
    expect(wrapper.text()).toContain('Sem acesso.')
  })

  it('cancelar volta', async () => {
    vi.stubGlobal('fetch', routeFetch(dirs))
    const wrapper = await mountView()
    await wrapper.find('[data-test="cancel"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.fullPath).toBe('/')
  })
})
