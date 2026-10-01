import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory, type Router } from 'vue-router'
import AppSidebar from '../AppSidebar.vue'
import { createAppRouter } from '../../../router'
import { useProjectsStore } from '../../../stores/projects'
import { jsonResponse, makeProject, makeSession } from '../../../test/factories'

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
