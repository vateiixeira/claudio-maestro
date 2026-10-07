import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory } from 'vue-router'
import { createAppRouter } from '../../router'
import MarkdownView from '../MarkdownView.vue'
import { jsonResponse, routeFetch } from '../../test/factories'

enableAutoUnmount(afterEach)
afterEach(() => {
  vi.unstubAllGlobals()
  // @ts-expect-error jsdom has no scrollIntoView; tests that need it define one.
  delete Element.prototype.scrollIntoView
})

const URL_A = 'GET /api/sessions/s1/markdown?path=docs%2Fplans%2Fa.md'
const fileA = (over: Partial<{ content: string; mtime: number }> = {}) => ({
  path: '/p/docs/plans/a.md', content: '# Plano A\n\n- [x] feito\n\nVer [spec](../specs/b.md).', mtime: 100, ...over,
})

async function open(path = '/sessions/s1/ver?caminho=docs%2Fplans%2Fa.md') {
  const router = createAppRouter(createMemoryHistory())
  await router.push(path)
  const wrapper = mount(MarkdownView, { props: { id: 's1' }, global: { plugins: [router] } })
  await flushPromises()
  return { wrapper, router }
}

describe('MarkdownView', () => {
  beforeEach(() => vi.stubGlobal('fetch', routeFetch({ [URL_A]: () => jsonResponse(fileA()) })))

  it('mostra nome, caminho e o documento renderizado', async () => {
    const { wrapper } = await open()
    expect(wrapper.find('[data-test="md-name"]').text()).toBe('a.md')
    expect(wrapper.find('[data-test="md-path"]').text()).toBe('/p/docs/plans/a.md')
    expect(wrapper.find('[data-test="md-body"] h1').text()).toBe('Plano A')
    expect(wrapper.find('[data-test="md-body"] input.task-checkbox').attributes('disabled')).toBeDefined()
    expect(document.title).toBe('Plano A · Cláudio Maestro')
  })

  it('sem título no arquivo, a aba usa o nome', async () => {
    vi.stubGlobal('fetch', routeFetch({ [URL_A]: () => jsonResponse(fileA({ content: 'texto' })) }))
    await open()
    expect(document.title).toBe('a.md · Cláudio Maestro')
  })

  it('link relativo parte da pasta do documento e navega na mesma aba', async () => {
    const fetchB = vi.fn(() => jsonResponse({ path: '/p/docs/specs/b.md', content: '# B', mtime: 1 }))
    vi.stubGlobal('fetch', routeFetch({ [URL_A]: () => jsonResponse(fileA()), 'GET /api/sessions/s1/markdown?path=%2Fp%2Fdocs%2Fspecs%2Fb.md': fetchB }))
    const { wrapper, router } = await open()
    await wrapper.find('[data-test="md-body"] a[data-md-view]').trigger('click', { button: 0 })
    await flushPromises()
    expect(router.currentRoute.value.query.caminho).toBe('/p/docs/specs/b.md')
    expect(fetchB).toHaveBeenCalled()
    expect(wrapper.find('[data-test="md-body"] h1').text()).toBe('B')
  })

  it('mostra o erro do servidor no lugar do documento', async () => {
    vi.stubGlobal('fetch', routeFetch({ [URL_A]: () => jsonResponse({ detail: 'O arquivo precisa estar dentro de um projeto.' }, 403) }))
    const { wrapper } = await open()
    expect(wrapper.find('[data-test="md-error"]').text()).toContain('O arquivo precisa estar dentro de um projeto.')
    expect(wrapper.find('[data-test="md-body"]').exists()).toBe(false)
  })

  it('sem caminho, avisa', async () => {
    const { wrapper } = await open('/sessions/s1/ver')
    expect(wrapper.find('[data-test="md-error"]').text()).toContain('Nenhum arquivo informado.')
  })

  it('ao voltar para a aba, só troca o conteúdo se o arquivo mudou', async () => {
    let version = fileA()
    const handler = vi.fn(() => jsonResponse(version))
    vi.stubGlobal('fetch', routeFetch({ [URL_A]: handler }))
    const { wrapper } = await open()
    const body = wrapper.find('[data-test="md-body"] > div').element
    document.dispatchEvent(new Event('visibilitychange'))
    await flushPromises()
    expect(handler).toHaveBeenCalledTimes(2)
    expect(wrapper.find('[data-test="md-body"] > div').element).toBe(body)
    version = fileA({ content: '# Plano A v2', mtime: 200 })
    window.dispatchEvent(new Event('focus'))
    await flushPromises()
    expect(wrapper.find('[data-test="md-body"] h1').text()).toBe('Plano A v2')
  })

  it('Abrir no editor manda o caminho resolvido', async () => {
    const editor = vi.fn((_init?: RequestInit) => new Response(null, { status: 204 }))
    vi.stubGlobal('fetch', routeFetch({ [URL_A]: () => jsonResponse(fileA()), 'POST /api/open-in-editor': editor }))
    const { wrapper } = await open()
    await wrapper.find('[data-test="md-open-editor"]').trigger('click')
    await flushPromises()
    // routeFetch hands the handler the `init` of the request.
    expect(JSON.parse(editor.mock.calls[0]![0]!.body as string)).toEqual({ path: '/p/docs/plans/a.md' })
  })

  it('a aba usa o primeiro título fora de blocos de código', async () => {
    const content = '```bash\n# comentário\n```\n\n# Título real\n'
    vi.stubGlobal('fetch', routeFetch({ [URL_A]: () => jsonResponse(fileA({ content })) }))
    await open()
    expect(document.title).toBe('Título real · Cláudio Maestro')
  })

  it('rola até a âncora mesmo se uma recarga atropelar a carga inicial', async () => {
    const scroll = vi.fn()
    Element.prototype.scrollIntoView = scroll
    const answers: Array<() => void> = []
    const handler = vi.fn(() => new Promise<Response>((resolve) => {
      answers.push(() => resolve(jsonResponse(fileA({ content: '# Plano A\n\n## Tarefa 1\n\ntexto' }))))
    }))
    vi.stubGlobal('fetch', routeFetch({ [URL_A]: handler }))
    const router = createAppRouter(createMemoryHistory())
    await router.push('/sessions/s1/ver?caminho=docs%2Fplans%2Fa.md#Tarefa%201')
    const wrapper = mount(MarkdownView, { props: { id: 's1' }, global: { plugins: [router] } })
    await flushPromises()
    window.dispatchEvent(new Event('focus'))
    await flushPromises()
    expect(handler).toHaveBeenCalledTimes(2)
    answers.forEach((answer) => answer())
    await flushPromises()
    expect(wrapper.find('#md-tarefa-1').exists()).toBe(true)
    expect(scroll).toHaveBeenCalled()
    expect((scroll.mock.contexts[0] as Element).id).toBe('md-tarefa-1')
  })

  it('falha numa recarga mantém o documento e avisa', async () => {
    let fail = false
    vi.stubGlobal('fetch', routeFetch({
      [URL_A]: () => (fail ? jsonResponse({ detail: 'Arquivo não encontrado.' }, 404) : jsonResponse(fileA())),
    }))
    const { wrapper } = await open()
    fail = true
    window.dispatchEvent(new Event('focus'))
    await flushPromises()
    expect(wrapper.find('[data-test="md-body"] h1').text()).toBe('Plano A')
    expect(wrapper.find('[data-test="md-error"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="md-notice"]').text()).toBe('Não foi possível atualizar: Arquivo não encontrado.')
  })

  it('falha na carga normal substitui o documento pelo erro', async () => {
    vi.stubGlobal('fetch', routeFetch({ [URL_A]: () => jsonResponse({ detail: 'Arquivo não encontrado.' }, 404) }))
    const { wrapper } = await open()
    expect(wrapper.find('[data-test="md-error"]').text()).toContain('Arquivo não encontrado.')
    expect(wrapper.find('[data-test="md-body"]').exists()).toBe(false)
  })

  it('trocar de documento pelo link interno volta ao topo de quem rola', async () => {
    const scrollTo = vi.fn()
    const fetchB = () => jsonResponse({ path: '/p/docs/specs/b.md', content: '# B', mtime: 1 })
    vi.stubGlobal('fetch', routeFetch({
      [URL_A]: () => jsonResponse(fileA()),
      'GET /api/sessions/s1/markdown?path=%2Fp%2Fdocs%2Fspecs%2Fb.md': fetchB,
    }))
    const scroller = document.createElement('div')
    scroller.className = 'overflow-y-auto'
    scroller.scrollTo = scrollTo as unknown as typeof scroller.scrollTo
    document.body.appendChild(scroller)
    const router = createAppRouter(createMemoryHistory())
    await router.push('/sessions/s1/ver?caminho=docs%2Fplans%2Fa.md')
    const wrapper = mount(MarkdownView, { props: { id: 's1' }, attachTo: scroller, global: { plugins: [router] } })
    await flushPromises()
    scrollTo.mockClear()
    await wrapper.find('[data-test="md-body"] a[data-md-view]').trigger('click', { button: 0 })
    await flushPromises()
    expect(scrollTo).toHaveBeenCalledWith({ top: 0 })
    wrapper.unmount()
    scroller.remove()
  })
})
