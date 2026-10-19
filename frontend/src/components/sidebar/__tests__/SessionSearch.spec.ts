import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory, type Router } from 'vue-router'
import AppSidebar from '../AppSidebar.vue'
import { createAppRouter } from '../../../router'
import { useLabelsStore } from '../../../stores/labels'
import { useProjectsStore } from '../../../stores/projects'
import { jsonResponse, makeLabel, makeProject, makeSession } from '../../../test/factories'

enableAutoUnmount(afterEach)

let pinia: Pinia
let router: Router

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  vi.useFakeTimers()
  router = createAppRouter(createMemoryHistory())
  const projects = useProjectsStore(pinia)
  projects.projects = [makeProject({ id: 1, name: 'loja-online', color: '#B28CFF' })]
  projects.loaded = true
})
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

function mountSidebar() {
  return mount(AppSidebar, { attachTo: document.body, global: { plugins: [pinia, router] } })
}

async function type(w: ReturnType<typeof mountSidebar>, value: string) {
  await w.find('[data-test="search-input"]').setValue(value)
}

describe('busca no menu lateral', () => {
  it('espera ~250 ms antes de consultar e mostra título, projeto, estado e data', async () => {
    const fetchMock = vi.fn(async (url: string) => {
      expect(url).toContain('/api/sessions/search?')
      expect(url).toContain('q=cupom')
      return jsonResponse([makeSession({ session_id: 'x', title: 'Cupom expirado', display_state: 'finished' })])
    })
    vi.stubGlobal('fetch', fetchMock)
    const w = mountSidebar()

    await type(w, 'cup')
    await vi.advanceTimersByTimeAsync(100)
    await type(w, 'cupom')
    await vi.advanceTimersByTimeAsync(200)
    expect(fetchMock).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(100)
    await flushPromises()

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const result = w.find('[data-test="search-result"]')
    expect(result.text()).toContain('Cupom expirado')
    expect(result.text()).toContain('loja-online')
    expect(result.text()).toContain('Finalizada')
  })

  it('resultados em espera comum têm o triângulo discreto, e o que precisa de você o laranja', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse([
      makeSession({ session_id: 'a', title: 'Calma', display_state: 'waiting', unread: false }),
      makeSession({ session_id: 'b', title: 'Pede', display_state: 'waiting', unread: true }),
    ])))
    const w = mountSidebar()
    await type(w, 'x')
    await vi.advanceTimersByTimeAsync(300)
    await flushPromises()
    const shapes = w.findAll('[data-test="search-result"]').map((r) => r.find('[data-shape]').attributes('data-shape'))
    expect(shapes).toEqual(['triangle-quiet', 'triangle'])
  })

  it('o ícone de estado tem 11 px e o rótulo diferencia espera comum de espera que pede você', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse([
      makeSession({ session_id: 'a', title: 'Calma', display_state: 'waiting', state: 'idle', unread: false }),
      makeSession({ session_id: 'b', title: 'Pede', display_state: 'waiting', state: 'awaiting_decision', pending_kind: 'plan' }),
    ])))
    const w = mountSidebar()
    await type(w, 'x')
    await vi.advanceTimersByTimeAsync(300)
    await flushPromises()
    const results = w.findAll('[data-test="search-result"]')
    expect(results[0]!.find('svg').attributes('width')).toBe('11')
    expect(results[0]!.text()).toContain('Sua vez')
    expect(results[1]!.text()).toContain('Aguardando você')
  })

  it('cada resultado mostra as etiquetas da sessão', async () => {
    useLabelsStore(pinia).labels = [1, 2].map((id) => makeLabel({ id, slug: `et${id}` }))
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse([
      makeSession({ session_id: 'a', title: 'Com etiquetas', label_ids: [1, 2] }),
      makeSession({ session_id: 'b', title: 'Sem etiquetas', label_ids: [] }),
    ])))
    const w = mountSidebar()
    await type(w, 'x')
    await vi.advanceTimersByTimeAsync(300)
    await flushPromises()
    const [first, second] = w.findAll('[data-test="search-result"]')
    const labels = first!.get('[data-test="search-labels"]')
    expect(labels.findAll('[data-test="label-badge"]').map((b) => b.text())).toEqual(['et1', 'et2'])
    // On its own line: after the title, before the project/state line.
    const html = first!.html()
    expect(html.indexOf('Com etiquetas')).toBeLessThan(html.indexOf('data-test="search-labels"'))
    expect(html.indexOf('data-test="search-labels"')).toBeLessThan(html.indexOf('loja-online'))
    expect(second!.find('[data-test="search-labels"]').exists()).toBe(false)
    expect(second!.find('[data-test="label-badges"]').exists()).toBe(false)
  })

  it('mostra até 3 etiquetas e "+N" na linha própria', async () => {
    useLabelsStore(pinia).labels = [1, 2, 3, 4].map((id) => makeLabel({ id, slug: `et${id}` }))
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse([makeSession({ session_id: 'a', label_ids: [1, 2, 3, 4] })])))
    const w = mountSidebar()
    await type(w, 'x')
    await vi.advanceTimersByTimeAsync(300)
    await flushPromises()
    const labels = w.get('[data-test="search-labels"]')
    expect(labels.findAll('[data-test="label-badge"]').map((b) => b.text())).toEqual(['et1', 'et2', 'et3'])
    expect(labels.get('[data-test="label-more"]').text()).toBe('+1')
  })

  it('descarta respostas antigas', async () => {
    const pending: Record<string, (r: Response) => void> = {}
    vi.stubGlobal('fetch', vi.fn((url: string) => new Promise<Response>((resolve) => {
      pending[new URL(url, 'http://x').searchParams.get('q')!] = resolve
    })))
    const w = mountSidebar()

    await type(w, 'velha')
    await vi.advanceTimersByTimeAsync(300)
    await type(w, 'nova')
    await vi.advanceTimersByTimeAsync(300)
    pending.nova!(jsonResponse([makeSession({ session_id: 'n', title: 'Resultado novo' })]))
    await flushPromises()
    pending.velha!(jsonResponse([makeSession({ session_id: 'v', title: 'Resultado velho' })]))
    await flushPromises()

    expect(w.text()).toContain('Resultado novo')
    expect(w.text()).not.toContain('Resultado velho')
  })

  it('mostra "Nenhuma sessão encontrada"', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse([])))
    const w = mountSidebar()
    await type(w, 'nada')
    await vi.advanceTimersByTimeAsync(300)
    await flushPromises()
    expect(w.text()).toContain('Nenhuma sessão encontrada')
  })

  it('o atalho Ctrl K não quebra em duas linhas', () => {
    const w = mountSidebar()
    const kbd = w.findAll('kbd').find((k) => k.text() === 'Ctrl K')!
    expect(kbd).toBeTruthy()
    expect(kbd.classes()).toEqual(expect.arrayContaining(['whitespace-nowrap', 'shrink-0']))
  })

  it('o erro da busca usa a cor de erro', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ detail: 'Busca fora do ar.' }, 500)))
    const w = mountSidebar()
    await type(w, 'x')
    await vi.advanceTimersByTimeAsync(300)
    await flushPromises()
    const alert = w.find('[role="alert"]')
    expect(alert.text()).toContain('Busca fora do ar.')
    expect(alert.classes()).toContain('text-diff-del-fg')
  })

  it('Ctrl+K e Cmd+K focam o campo', async () => {
    const w = mountSidebar()
    const input = w.find('[data-test="search-input"]').element as HTMLInputElement
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', ctrlKey: true }))
    expect(document.activeElement).toBe(input)
    input.blur()
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', metaKey: true }))
    expect(document.activeElement).toBe(input)
  })

  it('Enter abre o primeiro resultado e clique abre o escolhido', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse([
      makeSession({ session_id: 'a', title: 'Primeira' }),
      makeSession({ session_id: 'b', title: 'Segunda' }),
    ])))
    const push = vi.spyOn(router, 'push')
    const w = mountSidebar()
    await type(w, 'x')
    await vi.advanceTimersByTimeAsync(300)
    await flushPromises()

    await w.find('[data-test="search-input"]').trigger('keydown', { key: 'Enter' })
    expect(push).toHaveBeenLastCalledWith({ name: 'session', params: { id: 'a' } })

    await type(w, 'x2')
    await vi.advanceTimersByTimeAsync(300)
    await flushPromises()
    await w.findAll('[data-test="search-result"]')[1]!.trigger('click')
    expect(push).toHaveBeenLastCalledWith({ name: 'session', params: { id: 'b' } })
  })

  const withMatch = (overrides = {}) => ({
    ...makeSession({ session_id: 'a', title: 'Criar tarefa em card parado', ...overrides }),
    match: {
      at: 1760474500,
      parts: [
        { text: '…o sistema cria uma ', hit: false },
        { text: 'tarefa <b>automaticamente</b>', hit: true },
        { text: ' para o responsável…', hit: false },
      ],
    },
  })

  it('mostra o trecho achado na conversa, com o termo em <mark> e sem interpretar HTML', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse([withMatch()])))
    const w = mountSidebar()
    await type(w, 'tarefa')
    await vi.advanceTimersByTimeAsync(300)
    await flushPromises()

    const snippet = w.get('[data-test="search-snippet"]')
    expect(snippet.text()).toBe('…o sistema cria uma tarefa <b>automaticamente</b> para o responsável…')
    expect(snippet.findAll('mark').map((m) => m.text())).toEqual(['tarefa <b>automaticamente</b>'])
    expect(snippet.find('b').exists()).toBe(false)
    expect(snippet.classes()).toContain('line-clamp-2')
    // `block` would override the `display: -webkit-box` that line-clamp needs (jsdom cannot measure lines).
    expect(snippet.classes()).not.toContain('block')
  })

  it('resultado só por título não tem trecho', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse([makeSession({ session_id: 'a', title: 'Cupom expirado' })])))
    const w = mountSidebar()
    await type(w, 'cupom')
    await vi.advanceTimersByTimeAsync(300)
    await flushPromises()

    expect(w.find('[data-test="search-snippet"]').exists()).toBe(false)
  })

  it('clicar ou apertar Enter num resultado com trecho leva o termo buscado para a conversa', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse([withMatch(), makeSession({ session_id: 'b', title: 'Outra' })])))
    const push = vi.spyOn(router, 'push')
    const w = mountSidebar()
    await type(w, '  tarefa auto ')
    await vi.advanceTimersByTimeAsync(300)
    await flushPromises()

    await w.find('[data-test="search-input"]').trigger('keydown', { key: 'Enter' })
    expect(push).toHaveBeenLastCalledWith({ name: 'session', params: { id: 'a' }, query: { find: 'tarefa auto' } })

    await w.findAll('[data-test="search-result"]')[0]!.trigger('click')
    expect(push).toHaveBeenLastCalledWith({ name: 'session', params: { id: 'a' }, query: { find: 'tarefa auto' } })

    await w.findAll('[data-test="search-result"]')[1]!.trigger('click')
    expect(push).toHaveBeenLastCalledWith({ name: 'session', params: { id: 'b' } })
  })

  it('Esc limpa o campo e os resultados', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse([makeSession({ title: 'Achada' })])))
    const w = mountSidebar()
    await type(w, 'x')
    await vi.advanceTimersByTimeAsync(300)
    await flushPromises()
    expect(w.text()).toContain('Achada')

    await w.find('[data-test="search-input"]').trigger('keydown', { key: 'Escape' })
    expect((w.find('[data-test="search-input"]').element as HTMLInputElement).value).toBe('')
    expect(w.text()).not.toContain('Achada')
  })
})
