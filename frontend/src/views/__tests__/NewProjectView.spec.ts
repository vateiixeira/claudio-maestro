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
const lojaRepos = {
  repos: [
    { name: 'loja-online', rel_path: '.', path: '/home/vi/dev/loja-online', branch: 'main', detached: false },
    { name: 'api', rel_path: 'servicos/api', path: '/home/vi/dev/loja-online/servicos/api', branch: 'abc1234', detached: true },
  ],
  limit_reached: false,
}
const dirs = {
  'GET /api/fs/repos?path=%2Fhome%2Fvi%2Fdev%2Floja-online': () => jsonResponse(lojaRepos),
  'GET /api/fs/repos?path=%2Fhome%2Fvi%2Fnotas': () => jsonResponse({ repos: [], limit_reached: false }),
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

  describe('escolher pasta pelo sistema', () => {
    const pick = (w: Awaited<ReturnType<typeof mountView>>) => w.find('[data-test="pick-folder"]')

    it('seleciona a pasta devolvida e lista os repositórios dela', async () => {
      const fetchMock = routeFetch({ ...dirs, 'POST /api/fs/pick': () => jsonResponse({ path: '/home/vi/dev/loja-online' }) })
      vi.stubGlobal('fetch', fetchMock)
      const wrapper = await mountView()
      expect(pick(wrapper).text()).toContain('Escolher pasta…')

      await pick(wrapper).trigger('click')
      await flushPromises()

      expect(wrapper.find('[data-test="selected-path"]').text()).toBe('~/dev/loja-online')
      expect(wrapper.find<HTMLInputElement>('#project-name').element.value).toBe('loja-online')
      const repos = wrapper.findAll('[data-test="found-repo"]').map((r) => r.text())
      expect(repos).toEqual(['loja-onlinemain', 'servicos/apiHEAD solto · abc1234'])
      expect(wrapper.find('[data-test="repo-limit"]').exists()).toBe(false)
      expect(wrapper.find('[data-test="create"]').attributes('disabled')).toBeUndefined()
      expect(fetchMock.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1)
    })

    it('cancelar não muda nada e não mostra erro', async () => {
      vi.stubGlobal('fetch', routeFetch({ ...dirs, 'POST /api/fs/pick': () => jsonResponse({ path: null }) }))
      const wrapper = await mountView()
      await entry(wrapper, 'notas').trigger('click')
      await flushPromises()
      await pick(wrapper).trigger('click')
      await flushPromises()
      expect(wrapper.find('[data-test="selected-path"]').text()).toBe('~/notas')
      expect(wrapper.find('[data-test="pick-error"]').exists()).toBe(false)
      expect(pick(wrapper).attributes('disabled')).toBeUndefined()
    })

    it.each([
      [503, 'Nenhum seletor de pastas disponível neste computador.'],
      [504, 'O seletor demorou demais e foi fechado.'],
      [409, 'Já existe um seletor de pastas aberto.'],
      [403, 'Escolha uma pasta dentro da sua pasta pessoal.'],
    ])('erro %i aparece de forma legível e o navegador continua disponível', async (status, detail) => {
      vi.stubGlobal('fetch', routeFetch({ ...dirs, 'POST /api/fs/pick': () => jsonResponse({ detail }, status) }))
      const wrapper = await mountView()
      await pick(wrapper).trigger('click')
      await flushPromises()
      expect(wrapper.find('[data-test="pick-error"]').text()).toBe(detail)
      expect(wrapper.find('[data-test="pick-error"]').attributes('role')).toBe('alert')
      expect(wrapper.findAll('[data-test="dir"]').length).toBeGreaterThan(0)
      // Escolher uma pasta no navegador limpa o erro.
      await entry(wrapper, 'notas').trigger('click')
      expect(wrapper.find('[data-test="pick-error"]').exists()).toBe(false)
    })

    it('desabilita o botão enquanto o seletor está aberto', async () => {
      let resolve!: (r: Response) => void
      vi.stubGlobal('fetch', routeFetch({ ...dirs, 'POST /api/fs/pick': () => new Promise<Response>((r) => { resolve = r }) }))
      const wrapper = await mountView()
      await pick(wrapper).trigger('click')
      expect(pick(wrapper).attributes('disabled')).toBeDefined()
      expect(pick(wrapper).text()).toContain('Aguardando')
      resolve(jsonResponse({ path: null }))
      await flushPromises()
      expect(pick(wrapper).attributes('disabled')).toBeUndefined()
    })
  })

  describe('repositórios encontrados', () => {
    it('vêm de /api/fs/repos e mostram o aviso quando o limite foi atingido', async () => {
      vi.stubGlobal('fetch', routeFetch({
        ...dirs,
        'GET /api/fs/repos?path=%2Fhome%2Fvi%2Fnotas': () => jsonResponse({
          repos: [{ name: 'x', rel_path: 'a/x', path: '/home/vi/notas/a/x', branch: null, detached: false }],
          limit_reached: true,
        }),
      }))
      const wrapper = await mountView()
      await entry(wrapper, 'notas').trigger('click')
      await flushPromises()
      expect(wrapper.findAll('[data-test="found-repo"]').map((r) => r.text())).toEqual(['a/xbranch indisponível'])
      expect(wrapper.find('[data-test="repo-limit"]').text()).toBe('Mais de 50 repositórios; só os 50 primeiros serão acompanhados.')
    })

    it('pasta sem repositórios mostra "sem repositório git"', async () => {
      vi.stubGlobal('fetch', routeFetch(dirs))
      const wrapper = await mountView()
      await entry(wrapper, 'notas').trigger('click')
      await flushPromises()
      expect(wrapper.find('[data-test="found-repos"]').text()).toContain('sem repositório git')
    })

    it('falha ao listar mostra uma nota sem bloquear a criação', async () => {
      vi.stubGlobal('fetch', routeFetch({
        ...dirs,
        'GET /api/fs/repos?path=%2Fhome%2Fvi%2Fnotas': () => jsonResponse({ detail: 'Falhou.' }, 500),
      }))
      const wrapper = await mountView()
      await entry(wrapper, 'notas').trigger('click')
      await flushPromises()
      expect(wrapper.find('[data-test="repos-error"]').text()).toContain('Falhou.')
      expect(wrapper.find('[data-test="create"]').attributes('disabled')).toBeUndefined()
    })

    it('anuncia ao leitor de tela a busca e o erro da prévia', async () => {
      let release: (r: Response) => void = () => {}
      vi.stubGlobal('fetch', routeFetch({
        ...dirs,
        'GET /api/fs/repos?path=%2Fhome%2Fvi%2Fnotas': () => new Promise<Response>((r) => { release = r }),
      }))
      const wrapper = await mountView()
      await entry(wrapper, 'notas').trigger('click')
      await flushPromises()
      const loading = wrapper.find('[data-test="found-repos"] [role="status"]')
      expect(loading.text()).toContain('Procurando repositórios')
      release(jsonResponse({ detail: 'Falhou.' }, 500))
      await flushPromises()
      const error = wrapper.find('[data-test="repos-error"]')
      expect(error.attributes('role')).toBe('status')
    })

    it('ignora a resposta de uma pasta antiga que chega depois', async () => {
      const pending = new Map<string, (r: Response) => void>()
      vi.stubGlobal('fetch', vi.fn((url: string) => {
        if (url.startsWith('/api/fs/repos')) return new Promise<Response>((r) => pending.set(url, r))
        if (url === '/api/fs/dirs' || url.endsWith('%2Fhome%2Fvi')) return Promise.resolve(jsonResponse(home))
        return Promise.resolve(jsonResponse(dev))
      }))
      const wrapper = await mountView()
      await entry(wrapper, 'dev').trigger('click')
      await entry(wrapper, 'notas').trigger('click')
      const urls = [...pending.keys()]
      expect(urls).toHaveLength(2)
      const repo = (name: string) => ({ repos: [{ name, rel_path: name, path: `/x/${name}`, branch: 'main', detached: false }], limit_reached: false })
      pending.get(urls[1]!)!(jsonResponse(repo('novo')))
      await flushPromises()
      pending.get(urls[0]!)!(jsonResponse(repo('velho')))
      await flushPromises()
      expect(wrapper.findAll('[data-test="found-repo"]').map((r) => r.text())).toEqual(['novomain'])
    })
  })

  describe('cancelamento da prévia', () => {
    // Fake fetch that never answers on its own and rejects like the browser when aborted.
    function hangingFetch() {
      const signals = new Map<string, AbortSignal | undefined>()
      const fetchMock = vi.fn((url: string, init?: RequestInit) => {
        if (url.startsWith('/api/fs/repos')) {
          signals.set(url, init?.signal ?? undefined)
          return new Promise<Response>((_resolve, reject) => {
            init?.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
          })
        }
        if (url === '/api/fs/dirs' || url.endsWith('%2Fhome%2Fvi')) return Promise.resolve(jsonResponse(home))
        return Promise.resolve(jsonResponse(dev))
      })
      vi.stubGlobal('fetch', fetchMock)
      return signals
    }
    const devUrl = '/api/fs/repos?path=%2Fhome%2Fvi%2Fdev%2Fblog'
    const notasUrl = '/api/fs/repos?path=%2Fhome%2Fvi%2Fnotas'

    it('um novo clique aborta o pedido anterior, sem mostrar erro', async () => {
      const signals = hangingFetch()
      const wrapper = await mountView()
      await entry(wrapper, 'dev').trigger('dblclick')
      await flushPromises()
      await entry(wrapper, 'blog').trigger('click')
      await flushPromises()
      expect(signals.get(devUrl)?.aborted).toBe(false)
      await wrapper.find('[data-test="crumb"]').trigger('click')
      await flushPromises()
      await entry(wrapper, 'notas').trigger('click')
      await flushPromises()
      expect(signals.get(devUrl)?.aborted).toBe(true)
      expect(signals.get(notasUrl)?.aborted).toBe(false)
      expect(wrapper.find('[data-test="repos-error"]').exists()).toBe(false)
      expect(wrapper.find('[data-test="found-repos"] [role="status"]').text()).toContain('Procurando repositórios')
    })

    it('sair da tela aborta o pedido em andamento', async () => {
      const signals = hangingFetch()
      const wrapper = await mountView()
      await entry(wrapper, 'notas').trigger('click')
      await flushPromises()
      expect(signals.get(notasUrl)?.aborted).toBe(false)
      wrapper.unmount()
      expect(signals.get(notasUrl)?.aborted).toBe(true)
    })

    it('a resposta de um pedido já concluído ainda mostra os repositórios', async () => {
      vi.stubGlobal('fetch', routeFetch(dirs))
      const wrapper = await mountView()
      await entry(wrapper, 'notas').trigger('click')
      await flushPromises()
      expect(wrapper.find('[data-test="found-repos"]').text()).toContain('sem repositório git')
      expect(wrapper.find('[data-test="repos-error"]').exists()).toBe(false)
    })
  })
})
