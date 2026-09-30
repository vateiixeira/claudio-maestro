import { afterEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, nextTick, ref } from 'vue'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { useComposerSuggestions } from '../useComposerSuggestions'
import { jsonResponse, routeFetch } from '../../test/factories'
import type { SuggestionScope } from '../../types/api'

enableAutoUnmount(afterEach)
afterEach(() => vi.unstubAllGlobals())

const COMMANDS = [
  { name: 'commit', description: 'Cria commit', argument_hint: '' },
  { name: 'hello', description: 'Diz olá', argument_hint: '<nome>' },
]

function harness(scope = ref<SuggestionScope | null>({ sessionId: 's1' })) {
  let api!: ReturnType<typeof useComposerSuggestions>
  const text = ref('')
  const Comp = defineComponent({
    setup() {
      const textarea = ref<HTMLTextAreaElement | null>(null)
      api = useComposerSuggestions({ textarea, text, scope: () => scope.value })
      return () => h('textarea', { ref: textarea })
    },
  })
  const wrapper = mount(Comp, { attachTo: document.body })
  const el = wrapper.find('textarea').element as HTMLTextAreaElement
  async function type(value: string, cursor = value.length) {
    text.value = value
    el.value = value
    el.setSelectionRange(cursor, cursor)
    api.refresh()
    await flushPromises()
  }
  function key(k: string, extra: KeyboardEventInit = {}) {
    const event = new KeyboardEvent('keydown', { key: k, cancelable: true, ...extra })
    const handled = api.onKeydown(event)
    return { handled, event }
  }
  return { api, text, el, type, key, scope }
}

describe('menu /', () => {
  it('busca a lista uma vez por fonte e filtra no navegador', async () => {
    const fetch = routeFetch({ 'GET /api/sessions/s1/commands': () => jsonResponse(COMMANDS) })
    vi.stubGlobal('fetch', fetch)
    const t = harness()
    await t.type('/co')
    expect(t.api.isOpen.value).toBe(true)
    expect(t.api.items.value.map((i) => i.label)).toEqual(['/commit'])
    await t.type('/he')
    await t.type('')
    await t.type('/')
    expect(t.api.items.value.map((i) => i.label)).toEqual(['/commit', '/hello'])
    expect(fetch).toHaveBeenCalledTimes(1)
  })

  it('mostra carregando e depois erro; reabrir tenta de novo', async () => {
    let fail = true
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/sessions/s1/commands': () => (fail ? jsonResponse({ detail: 'CLI não encontrado.' }, 502) : jsonResponse(COMMANDS)),
    }))
    const t = harness()
    t.text.value = '/'
    t.el.value = '/'
    t.el.setSelectionRange(1, 1)
    t.api.refresh()
    expect(t.api.status.value).toBe('loading')
    await flushPromises()
    expect(t.api.status.value).toBe('error')
    expect(t.api.error.value).toBe('CLI não encontrado.')
    fail = false
    await t.type('')
    await t.type('/')
    expect(t.api.status.value).toBe('ready')
  })

  it('teclado: setas com volta, Enter escolhe e põe espaço', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/sessions/s1/commands': () => jsonResponse(COMMANDS) }))
    const t = harness()
    await t.type('/')
    expect(t.api.active.value).toBe(0)
    t.key('ArrowUp')
    expect(t.api.active.value).toBe(1)
    t.key('ArrowDown')
    expect(t.api.active.value).toBe(0)
    const { handled, event } = t.key('Enter')
    expect(handled).toBe(true)
    expect(event.defaultPrevented).toBe(true)
    expect(t.text.value).toBe('/commit ')
    expect(t.el.selectionStart).toBe(8)
    expect(t.api.isOpen.value).toBe(false)
  })

  it('Tab escolhe; Shift+Enter e composição não são tratados', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/sessions/s1/commands': () => jsonResponse(COMMANDS) }))
    const t = harness()
    await t.type('/he')
    expect(t.key('Enter', { shiftKey: true }).handled).toBe(false)
    expect(t.key('Enter', { isComposing: true }).handled).toBe(false)
    t.key('Tab')
    expect(t.text.value).toBe('/hello ')
  })

  it('Enter com menu aberto e sem itens não faz nada', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/sessions/s1/commands': () => jsonResponse(COMMANDS) }))
    const t = harness()
    await t.type('/zzz')
    const { handled, event } = t.key('Enter')
    expect(handled).toBe(true)
    expect(event.defaultPrevented).toBe(true)
    expect(t.text.value).toBe('/zzz')
  })

  it('Esc fecha e suprime até sair do trecho', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/sessions/s1/commands': () => jsonResponse(COMMANDS) }))
    const t = harness()
    await t.type('/co')
    const { event } = t.key('Escape')
    expect(t.api.isOpen.value).toBe(false)
    expect(event.defaultPrevented).toBe(true)
    await t.type('/com')
    expect(t.api.isOpen.value).toBe(false)
    await t.type('/com ')
    await t.type('/com /')
    expect(t.api.isOpen.value).toBe(true)
  })

  it('trocar a fonte zera a lista e fecha', async () => {
    const fetch = routeFetch({
      'GET /api/projects/1/commands': () => jsonResponse(COMMANDS),
      'GET /api/projects/2/commands': () => jsonResponse([]),
    })
    vi.stubGlobal('fetch', fetch)
    const scope = ref<SuggestionScope | null>({ projectId: 1 })
    const t = harness(scope)
    await t.type('/')
    scope.value = { projectId: 2 }
    await nextTick()
    expect(t.api.isOpen.value).toBe(false)
    await t.type('')
    await t.type('/')
    expect(t.api.items.value).toEqual([])
    expect(fetch).toHaveBeenCalledTimes(2)
  })

  it('refresh com a mesma query mantém o item marcado', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/sessions/s1/commands': () => jsonResponse(COMMANDS) }))
    const t = harness()
    await t.type('/')
    t.api.refresh()
    t.key('ArrowDown')
    expect(t.api.active.value).toBe(1)
    t.api.refresh()
    await flushPromises()
    expect(t.api.active.value).toBe(1)
    await t.type('/h')
    expect(t.api.active.value).toBe(0)
  })

  it('trocar a fonte com a busca em voo busca a lista da fonte nova', async () => {
    let release!: (r: Response) => void
    const pending = new Promise<Response>((resolve) => { release = resolve })
    const fetch = routeFetch({
      'GET /api/projects/1/commands': () => pending,
      'GET /api/projects/2/commands': () => jsonResponse([COMMANDS[1]]),
    })
    vi.stubGlobal('fetch', fetch)
    const scope = ref<SuggestionScope | null>({ projectId: 1 })
    const t = harness(scope)
    await t.type('/')
    expect(t.api.status.value).toBe('loading')
    scope.value = { projectId: 2 }
    await nextTick()
    await t.type('')
    await t.type('/')
    release(jsonResponse(COMMANDS))
    await flushPromises()
    expect(fetch).toHaveBeenCalledTimes(2)
    expect(t.api.status.value).toBe('ready')
    expect(t.api.items.value.map((i) => i.label)).toEqual(['/hello'])
  })

  it('com erro, digitar mais não refaz a busca; fechar e reabrir refaz', async () => {
    const fetch = routeFetch({ 'GET /api/sessions/s1/commands': () => jsonResponse({ detail: 'Falhou.' }, 502) })
    vi.stubGlobal('fetch', fetch)
    const t = harness()
    await t.type('/')
    expect(t.api.status.value).toBe('error')
    await t.type('/c')
    await t.type('/co')
    expect(fetch).toHaveBeenCalledTimes(1)
    expect(t.api.status.value).toBe('error')
    expect(t.api.error.value).toBe('Falhou.')
    await t.type('')
    await t.type('/')
    expect(fetch).toHaveBeenCalledTimes(2)
  })

  it('perder o foco fecha sem suprimir', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/sessions/s1/commands': () => jsonResponse(COMMANDS) }))
    const t = harness()
    await t.type('/co')
    t.api.onBlur()
    expect(t.api.isOpen.value).toBe(false)
    await t.type('/com')
    expect(t.api.isOpen.value).toBe(true)
  })
})
