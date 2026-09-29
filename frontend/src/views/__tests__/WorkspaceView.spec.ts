import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory, type Router } from 'vue-router'
import { createAppRouter } from '../../router'
import { jsonResponse, makeEvent, makeProject, makeSnapshot, routeFetch } from '../../test/factories'
import { useProjectsStore } from '../../stores/projects'
import { DEFAULT_WIDTH, MIN_WIDTH, useLayoutStore } from '../../stores/layout'

const fake = vi.hoisted(() => ({
  session: new Map<string, Set<(e: unknown) => void>>(),
  reconnect: new Set<() => void>(),
}))
vi.mock('../../api/socket', () => ({
  useEventSocket: () => ({
    onSession: (id: string, h: (e: unknown) => void) => {
      const set = fake.session.get(id) ?? new Set()
      set.add(h)
      fake.session.set(id, set)
      return () => {
        set.delete(h)
        if (set.size === 0) fake.session.delete(id)
      }
    },
    onReconnect: (h: () => void) => { fake.reconnect.add(h); return () => fake.reconnect.delete(h) },
    onOpen: (h: () => void) => { fake.reconnect.add(h); return () => fake.reconnect.delete(h) },
  }),
}))

import WorkspaceView from '../WorkspaceView.vue'

enableAutoUnmount(afterEach)
let pinia: Pinia
let router: Router

const text = (id: string, t: string) => ({ type: 'text', id, text: t, streaming: false, parent_tool_use_id: null })
const emit = (sessionId: string, e: unknown) => fake.session.get(sessionId)?.forEach((h) => h(e))

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  fake.session.clear()
  fake.reconnect.clear()
  const projects = useProjectsStore(pinia)
  projects.projects = [makeProject({ id: 1 })]
  projects.loaded = true
  Element.prototype.scrollIntoView = vi.fn()
  vi.stubGlobal('fetch', routeFetch({
    'GET /api/sessions/s1': () => jsonResponse(makeSnapshot({ title: 'Sessão A' })),
    'GET /api/sessions/s2': () => jsonResponse(makeSnapshot({ session_id: 's2', title: 'Sessão B' })),
    'GET /api/sessions/sumiu': () => jsonResponse({ detail: 'Sessão não encontrada.' }, 404),
    'POST /api/sessions/s1/seen': () => jsonResponse(undefined, 204),
    'POST /api/sessions/s2/seen': () => jsonResponse(undefined, 204),
  }))
})
afterEach(() => vi.unstubAllGlobals())

async function mountAt(path: string) {
  router = createAppRouter(createMemoryHistory())
  await router.push(path)
  const w = mount(WorkspaceView, { global: { plugins: [pinia, router] }, attachTo: document.body })
  await flushPromises()
  return w
}

async function go(path: string) {
  await router.push(path)
  await flushPromises()
}

const columns = (w: ReturnType<typeof mount>) => w.findAll('[data-test="session-column"]')

describe('área de colunas', () => {
  it('sem colunas mostra a tela inicial', async () => {
    const w = await mountAt('/')
    expect(columns(w)).toHaveLength(0)
    expect(w.text()).toContain('Escolha um projeto ou uma sessão')
  })

  it('abrir uma sessão cria a coluna e não duplica', async () => {
    const w = await mountAt('/sessions/s1')
    expect(columns(w)).toHaveLength(1)
    await go('/')
    await go('/sessions/s1')
    expect(columns(w)).toHaveLength(1)
    await go('/sessions/s2')
    expect(columns(w)).toHaveLength(2)
    expect(useLayoutStore().columns).toEqual(['s1', 's2'])
    expect(w.text()).toContain('Sessão A')
    expect(w.text()).toContain('Sessão B')
  })

  it('fechar remove só aquela coluna e só a assinatura dela', async () => {
    const w = await mountAt('/sessions/s1')
    await go('/sessions/s2')
    expect([...fake.session.keys()].sort()).toEqual(['s1', 's2'])
    await columns(w)[0]!.find('button[aria-label="Fechar coluna"]').trigger('click')
    await flushPromises()
    expect(columns(w)).toHaveLength(1)
    expect(useLayoutStore().columns).toEqual(['s2'])
    expect([...fake.session.keys()]).toEqual(['s2'])
    expect(fake.reconnect.size).toBe(1)
  })

  it('fechar a coluna da rota atual volta para /', async () => {
    const w = await mountAt('/sessions/s1')
    await columns(w)[0]!.find('button[aria-label="Fechar coluna"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.fullPath).toBe('/')
    expect(columns(w)).toHaveLength(0)
  })

  it('cada coluna recebe só os eventos da própria sessão', async () => {
    const w = await mountAt('/sessions/s1')
    await go('/sessions/s2')
    emit('s1', makeEvent('item.upsert', text('a', 'só da A'), 1, 's1'))
    emit('s2', makeEvent('item.upsert', text('b', 'só da B'), 1, 's2'))
    await flushPromises()
    const [a, b] = columns(w)
    expect(a!.text()).toContain('só da A')
    expect(a!.text()).not.toContain('só da B')
    expect(b!.text()).toContain('só da B')
    expect(b!.text()).not.toContain('só da A')
  })

  it('o rascunho não vaza entre colunas', async () => {
    const w = await mountAt('/sessions/s1')
    await go('/sessions/s2')
    await columns(w)[0]!.find('textarea').setValue('rascunho da A')
    expect((columns(w)[1]!.find('textarea').element as HTMLTextAreaElement).value).toBe('')
    await go('/sessions/s1')
    expect((columns(w)[0]!.find('textarea').element as HTMLTextAreaElement).value).toBe('rascunho da A')
  })

  it('sessão inexistente sai do layout sem erro', async () => {
    const layout = useLayoutStore(pinia)
    layout.open('s1')
    layout.open('sumiu')
    const w = await mountAt('/')
    expect(layout.columns).toEqual(['s1'])
    expect(columns(w)).toHaveLength(1)
    expect(w.find('[role="alert"]').exists()).toBe(false)
  })

  it('redimensiona pelo teclado respeitando o mínimo', async () => {
    const w = await mountAt('/sessions/s1')
    const handle = w.find('[role="separator"]')
    expect(handle.attributes('tabindex')).toBe('0')
    expect(handle.attributes('aria-valuenow')).toBe(String(DEFAULT_WIDTH))
    await handle.trigger('keydown', { key: 'ArrowRight' })
    expect(useLayoutStore().widthOf('s1')).toBeGreaterThan(DEFAULT_WIDTH)
    for (let i = 0; i < 40; i++) await handle.trigger('keydown', { key: 'ArrowLeft' })
    expect(useLayoutStore().widthOf('s1')).toBe(MIN_WIDTH)
    expect(handle.attributes('aria-valuenow')).toBe(String(MIN_WIDTH))
    expect((columns(w)[0]!.element as HTMLElement).style.width).toBe(`${MIN_WIDTH}px`)
  })

  it('redimensiona arrastando a borda respeitando o mínimo', async () => {
    const w = await mountAt('/sessions/s1')
    const handle = w.find('[role="separator"]')
    handle.element.dispatchEvent(new MouseEvent('pointerdown', { clientX: 500, button: 0, bubbles: true }))
    window.dispatchEvent(new MouseEvent('pointermove', { clientX: 600 }))
    expect(useLayoutStore().widthOf('s1')).toBe(DEFAULT_WIDTH + 100)
    window.dispatchEvent(new MouseEvent('pointermove', { clientX: 0 }))
    expect(useLayoutStore().widthOf('s1')).toBe(MIN_WIDTH)
    window.dispatchEvent(new MouseEvent('pointerup', { clientX: 0 }))
    window.dispatchEvent(new MouseEvent('pointermove', { clientX: 900 }))
    expect(useLayoutStore().widthOf('s1')).toBe(MIN_WIDTH)
  })

  describe('com IntersectionObserver', () => {
    const observers: FakeObserver[] = []
    class FakeObserver {
      targets = new Set<Element>()
      disconnected = false
      cb: IntersectionObserverCallback
      options?: IntersectionObserverInit
      constructor(cb: IntersectionObserverCallback, options?: IntersectionObserverInit) {
        this.cb = cb
        this.options = options
        observers.push(this)
      }
      observe(el: Element) { this.targets.add(el) }
      unobserve(el: Element) { this.targets.delete(el) }
      disconnect() { this.disconnected = true; this.targets.clear() }
      report(visible: boolean) {
        this.cb([...this.targets].map((target) => ({ target, isIntersecting: visible })) as never, this as never)
      }
    }
    const seenCalls = () => (fetch as ReturnType<typeof vi.fn>).mock.calls.filter(([url]) => String(url).endsWith('/seen')).length

    beforeEach(() => {
      observers.length = 0
      vi.stubGlobal('IntersectionObserver', FakeObserver)
    })

    it('só marca como vista depois de o observador dizer que a coluna aparece', async () => {
      await mountAt('/sessions/s1')
      await new Promise((r) => setTimeout(r, 400))
      expect(seenCalls()).toBe(0)
      const live = observers.find((o) => !o.disconnected)!
      live.report(true)
      await new Promise((r) => setTimeout(r, 400))
      expect(seenCalls()).toBe(1)
    })

    it('recria o observador quando o contêiner volta depois de fechar tudo', async () => {
      const w = await mountAt('/sessions/s1')
      await columns(w)[0]!.find('button[aria-label="Fechar coluna"]').trigger('click')
      await flushPromises()
      await go('/sessions/s2')
      const live = observers.filter((o) => !o.disconnected)
      expect(live).toHaveLength(1)
      const strip = w.find('[aria-label="Sessões abertas"]').element
      expect(live[0]!.options?.root).toBe(strip)
      expect(live[0]!.targets.size).toBe(1)
    })
  })
})
