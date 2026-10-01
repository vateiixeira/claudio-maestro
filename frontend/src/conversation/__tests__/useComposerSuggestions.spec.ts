import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
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
  return { api, text, el, type, key, scope, wrapper }
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

  it('sem fonte (modal sem projeto) o menu não abre nem fica em carregando', async () => {
    const fetch = routeFetch({})
    vi.stubGlobal('fetch', fetch)
    const t = harness(ref<SuggestionScope | null>(null))
    await t.type('/co')
    expect(t.api.isOpen.value).toBe(false)
    await t.type('@fs')
    expect(t.api.isOpen.value).toBe(false)
    expect(t.api.status.value).not.toBe('loading')
    expect(fetch).not.toHaveBeenCalled()
  })

  it('trocar de / para @ antes dos comandos chegarem não mostra "ready" sem arquivos', async () => {
    let release!: (r: Response) => void
    const pending = new Promise<Response>((resolve) => { release = resolve })
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/sessions/s1/commands': () => pending,
      'GET /api/sessions/s1/files?q=a': () => jsonResponse([]),
    }))
    const t = harness()
    await t.type('/')
    await t.type('@a')
    expect(t.api.status.value).toBe('loading')
    release(jsonResponse(COMMANDS))
    await flushPromises()
    expect(t.api.kind.value).toBe('mention')
    expect(t.api.status.value).toBe('loading')
    expect(t.api.commands.value).toHaveLength(2)
  })

  it('erro dos comandos com o gatilho já em @ não vira erro do menu de arquivos', async () => {
    let release!: (r: Response) => void
    const pending = new Promise<Response>((resolve) => { release = resolve })
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/sessions/s1/commands': () => pending,
      'GET /api/sessions/s1/files?q=a': () => jsonResponse([]),
    }))
    const t = harness()
    await t.type('/')
    await t.type('@a')
    release(jsonResponse({ detail: 'Falhou.' }, 502))
    await flushPromises()
    expect(t.api.status.value).toBe('loading')
    expect(t.api.error.value).toBeNull()
  })

  it('voltar de @ para / com os comandos ainda em voo mostra carregando', async () => {
    let release!: (r: Response) => void
    const pending = new Promise<Response>((resolve) => { release = resolve })
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/sessions/s1/commands': () => pending,
      'GET /api/sessions/s1/files?q=a': () => jsonResponse([]),
    }))
    const t = harness()
    await t.type('/')
    await t.type('@a')
    await t.type('/')
    expect(t.api.status.value).toBe('loading')
    release(jsonResponse(COMMANDS))
    await flushPromises()
    expect(t.api.status.value).toBe('ready')
    expect(t.api.items.value).toHaveLength(2)
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

describe('menu @', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  const FILES = [
    { path: 'backend/', name: 'backend', type: 'directory' },
    { path: 'backend/fs.py', name: 'fs.py', type: 'file' },
  ]

  it('espera 200 ms antes de buscar', async () => {
    const fetch = routeFetch({ 'GET /api/sessions/s1/files?q=fs': () => jsonResponse(FILES) })
    vi.stubGlobal('fetch', fetch)
    const t = harness()
    await t.type('@fs')
    expect(t.api.status.value).toBe('loading')
    expect(fetch).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(199)
    expect(fetch).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(1)
    await flushPromises()
    expect(t.api.items.value.map((i) => i.label)).toEqual(['backend/', 'fs.py'])
    expect(t.api.items.value[1].detail).toBe('backend')
  })

  it('monta os itens de arquivo e de pasta', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/sessions/s1/files?q=b': () => jsonResponse([...FILES, { path: 'README.md', name: 'README.md', type: 'file' }]) }))
    const t = harness()
    await t.type('@b')
    await vi.advanceTimersByTimeAsync(200)
    await flushPromises()
    expect(t.api.items.value).toEqual([
      { key: 'd:backend/', kind: 'directory', label: 'backend/', detail: '', hint: '', insert: '@backend/' },
      { key: 'f:backend/fs.py', kind: 'file', label: 'fs.py', detail: 'backend', hint: '', insert: '@backend/fs.py' },
      { key: 'f:README.md', kind: 'file', label: 'README.md', detail: '', hint: '', insert: '@README.md' },
    ])
  })

  it('resposta velha descartada', async () => {
    let releaseOld!: () => void
    const old = new Promise<Response>((resolve) => { releaseOld = () => resolve(jsonResponse([{ path: 'velho.py', name: 'velho.py', type: 'file' }])) })
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/sessions/s1/files?q=ab': () => old,
      'GET /api/sessions/s1/files?q=abc': () => jsonResponse([{ path: 'abc.py', name: 'abc.py', type: 'file' }]),
    }))
    const t = harness()
    await t.type('@ab')
    await vi.advanceTimersByTimeAsync(200)
    await t.type('@abc')
    await vi.advanceTimersByTimeAsync(200)
    await flushPromises()
    releaseOld()
    await flushPromises()
    expect(t.api.items.value.map((i) => i.label)).toEqual(['abc.py'])
  })

  it('digitar de novo antes dos 200 ms cancela a busca anterior', async () => {
    const fetch = routeFetch({ 'GET /api/sessions/s1/files?q=abc': () => jsonResponse([]) })
    vi.stubGlobal('fetch', fetch)
    const t = harness()
    await t.type('@a')
    await vi.advanceTimersByTimeAsync(100)
    await t.type('@ab')
    await vi.advanceTimersByTimeAsync(100)
    await t.type('@abc')
    await vi.advanceTimersByTimeAsync(200)
    await flushPromises()
    expect(fetch).toHaveBeenCalledTimes(1)
  })

  it('nas buscas seguintes os itens antigos ficam até a resposta nova', async () => {
    let release!: (r: Response) => void
    const pending = new Promise<Response>((resolve) => { release = resolve })
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/sessions/s1/files?q=f': () => jsonResponse(FILES),
      'GET /api/sessions/s1/files?q=fs': () => pending,
    }))
    const t = harness()
    await t.type('@f')
    await vi.advanceTimersByTimeAsync(200)
    await flushPromises()
    await t.type('@fs')
    await vi.advanceTimersByTimeAsync(200)
    expect(t.api.status.value).toBe('ready')
    expect(t.api.items.value).toHaveLength(2)
    release(jsonResponse([FILES[1]]))
    await flushPromises()
    expect(t.api.items.value.map((i) => i.label)).toEqual(['fs.py'])
  })

  it('arquivo escolhido: @caminho com espaço, fecha e entra no conjunto de menções', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/sessions/s1/files?q=fs': () => jsonResponse(FILES) }))
    const t = harness()
    await t.type('veja @fs')
    await vi.advanceTimersByTimeAsync(200)
    await flushPromises()
    t.key('ArrowDown')
    t.key('Enter')
    expect(t.text.value).toBe('veja @backend/fs.py ')
    expect(t.api.isOpen.value).toBe(false)
    expect([...t.api.mentions.value]).toEqual(['@backend/fs.py'])
  })

  it('pasta com Tab: sem espaço, menu continua e busca o novo termo', async () => {
    const fetch = routeFetch({
      'GET /api/sessions/s1/files?q=back': () => jsonResponse(FILES),
      'GET /api/sessions/s1/files?q=backend%2F': () => jsonResponse([FILES[1]]),
    })
    vi.stubGlobal('fetch', fetch)
    const t = harness()
    await t.type('@back')
    await vi.advanceTimersByTimeAsync(200)
    await flushPromises()
    t.key('Tab')
    expect(t.text.value).toBe('@backend/')
    expect(t.api.isOpen.value).toBe(true)
    expect([...t.api.mentions.value]).toEqual([])
    await vi.advanceTimersByTimeAsync(200)
    await flushPromises()
    expect(t.api.items.value.map((i) => i.label)).toEqual(['fs.py'])
  })

  it('pasta com clique: igual ao Tab', async () => {
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/sessions/s1/files?q=back': () => jsonResponse(FILES),
      'GET /api/sessions/s1/files?q=backend%2F': () => jsonResponse([FILES[1]]),
    }))
    const t = harness()
    await t.type('@back')
    await vi.advanceTimersByTimeAsync(200)
    await flushPromises()
    t.api.choose(0, 'click')
    expect(t.text.value).toBe('@backend/')
    expect(t.api.isOpen.value).toBe(true)
  })

  it('pasta com Enter: com espaço, fecha e entra no conjunto', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/sessions/s1/files?q=back': () => jsonResponse(FILES) }))
    const t = harness()
    await t.type('@back')
    await vi.advanceTimersByTimeAsync(200)
    await flushPromises()
    t.key('Enter')
    expect(t.text.value).toBe('@backend/ ')
    expect(t.api.isOpen.value).toBe(false)
    expect([...t.api.mentions.value]).toEqual(['@backend/'])
  })

  it('arquivo com Tab também fecha com espaço', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/sessions/s1/files?q=fs': () => jsonResponse(FILES) }))
    const t = harness()
    await t.type('@fs')
    await vi.advanceTimersByTimeAsync(200)
    await flushPromises()
    t.key('ArrowDown')
    t.key('Tab')
    expect(t.text.value).toBe('@backend/fs.py ')
    expect(t.api.isOpen.value).toBe(false)
  })

  it('erro da busca aparece e a próxima mudança tenta de novo', async () => {
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/sessions/s1/files?q=x': () => jsonResponse({ detail: 'Falha ao listar os arquivos: x' }, 502),
      'GET /api/sessions/s1/files?q=xy': () => jsonResponse([]),
    }))
    const t = harness()
    await t.type('@x')
    await vi.advanceTimersByTimeAsync(200)
    await flushPromises()
    expect(t.api.status.value).toBe('error')
    expect(t.api.error.value).toBe('Falha ao listar os arquivos: x')
    await t.type('@xy')
    await vi.advanceTimersByTimeAsync(200)
    await flushPromises()
    expect(t.api.status.value).toBe('ready')
  })

  it('caminho com espaço vai entre aspas', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/sessions/s1/files?q=meu': () => jsonResponse([{ path: 'meu arquivo.md', name: 'meu arquivo.md', type: 'file' }]) }))
    const t = harness()
    await t.type('@meu')
    await vi.advanceTimersByTimeAsync(200)
    await flushPromises()
    t.key('Enter')
    expect(t.text.value).toBe('@"meu arquivo.md" ')
  })

  it('fechar cancela a busca agendada', async () => {
    const fetch = routeFetch({ 'GET /api/sessions/s1/files?q=fs': () => jsonResponse(FILES) })
    vi.stubGlobal('fetch', fetch)
    const t = harness()
    await t.type('@fs')
    t.api.close()
    await vi.advanceTimersByTimeAsync(500)
    expect(fetch).not.toHaveBeenCalled()
  })

  it('desmontar cancela a busca agendada', async () => {
    const fetch = routeFetch({ 'GET /api/sessions/s1/files?q=fs': () => jsonResponse(FILES) })
    vi.stubGlobal('fetch', fetch)
    const t = harness()
    await t.type('@fs')
    t.wrapper.unmount()
    await vi.advanceTimersByTimeAsync(500)
    expect(fetch).not.toHaveBeenCalled()
  })

  it('a seleção só volta ao primeiro item com lista nova ou termo novo', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/sessions/s1/files?q=f': () => jsonResponse(FILES) }))
    const t = harness()
    await t.type('@f')
    await vi.advanceTimersByTimeAsync(200)
    await flushPromises()
    t.key('ArrowDown')
    expect(t.api.active.value).toBe(1)
    t.api.refresh()
    await vi.advanceTimersByTimeAsync(500)
    await flushPromises()
    expect(t.api.active.value).toBe(1)
  })

  it('trocar de @ para / cancela a busca e mostra os comandos', async () => {
    const fetch = routeFetch({
      'GET /api/sessions/s1/files?q=a': () => jsonResponse(FILES),
      'GET /api/sessions/s1/commands': () => jsonResponse(COMMANDS),
    })
    vi.stubGlobal('fetch', fetch)
    const t = harness()
    await t.type('@a')
    await t.type('/co')
    await vi.advanceTimersByTimeAsync(500)
    await flushPromises()
    expect(fetch).toHaveBeenCalledTimes(1)
    expect(t.api.kind.value).toBe('command')
    expect(t.api.items.value.map((i) => i.label)).toEqual(['/commit'])
  })
})

describe('dica de argumentos e poda das menções', () => {
  it('argumentHint só com o texto igual a /nome ', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/sessions/s1/commands': () => jsonResponse(COMMANDS) }))
    const t = harness()
    await t.type('/he')
    t.key('Enter')
    expect(t.text.value).toBe('/hello ')
    expect(t.api.argumentHint.value).toBe('<nome>')
    t.text.value = '/hello V'
    await nextTick()
    expect(t.api.argumentHint.value).toBe('')
  })

  it('argumentHint vazio para comando sem dica e para comando desconhecido', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/sessions/s1/commands': () => jsonResponse(COMMANDS) }))
    const t = harness()
    await t.type('/co')
    t.key('Enter')
    expect(t.text.value).toBe('/commit ')
    expect(t.api.argumentHint.value).toBe('')
    t.text.value = '/outro '
    await nextTick()
    expect(t.api.argumentHint.value).toBe('')
  })

  it('menção sai do conjunto quando o texto deixa de contê-la', async () => {
    vi.useFakeTimers()
    try {
      vi.stubGlobal('fetch', routeFetch({
        'GET /api/sessions/s1/files?q=fs': () => jsonResponse([{ path: 'backend/fs.py', name: 'fs.py', type: 'file' }]),
      }))
      const t = harness()
      await t.type('veja @fs')
      await vi.advanceTimersByTimeAsync(200)
      await flushPromises()
      t.key('Enter')
      expect([...t.api.mentions.value]).toEqual(['@backend/fs.py'])
      t.text.value = 'veja @backend/fs.py e mais'
      await nextTick()
      expect(t.api.mentions.value.size).toBe(1)
      t.text.value = 'veja '
      await nextTick()
      expect(t.api.mentions.value.size).toBe(0)
    } finally {
      vi.useRealTimers()
    }
  })
})
