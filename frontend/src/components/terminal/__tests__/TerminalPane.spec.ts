import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'

const fake = vi.hoisted(() => {
  const state = {
    instances: [] as Array<Record<string, any>>,
    fits: 0,
    observers: [] as Array<() => void>,
    holdWrites: false,
  }
  return state
})

vi.mock('@xterm/xterm', () => {
  class Terminal {
    cols = 80
    rows = 3
    written: string[] = []
    resets = 0
    disposed = false
    selection = ''
    opened: HTMLElement | null = null
    options: Record<string, any>
    dataCb: ((data: string) => void) | null = null
    selectionCb: (() => void) | null = null
    lines = ['$ ls   ', 'a.txt', '   ']
    buffer = { active: { viewportY: 0, getLine: (i: number) => (this.lines[i] === undefined ? undefined : { translateToString: (trim: boolean) => (trim ? this.lines[i].trimEnd() : this.lines[i]) }) } }
    constructor(options: Record<string, any>) {
      this.options = options
      fake.instances.push(this as unknown as Record<string, any>)
    }
    loadAddon() {}
    open(el: HTMLElement) { this.opened = el }
    // `hold` keeps the write callbacks until `flush`; `onWrite` lets a test play the replies xterm would give while parsing.
    hold = fake.holdWrites
    pending: Array<() => void> = []
    onWrite: ((data: string) => void) | null = null
    write(data: string, cb?: () => void) {
      this.written.push(data)
      this.onWrite?.(data)
      if (!cb) return
      if (this.hold) this.pending.push(cb)
      else cb()
    }
    flush() { this.pending.splice(0).forEach((cb) => cb()) }
    reset() { this.resets += 1; this.written = [] }
    onData(cb: (data: string) => void) { this.dataCb = cb; return { dispose() {} } }
    onSelectionChange(cb: () => void) { this.selectionCb = cb; return { dispose() {} } }
    hasSelection() { return this.selection !== '' }
    getSelection() { return this.selection }
    getSelectionPosition() { return this.selection ? { start: { x: 0, y: 0 }, end: { x: 4, y: 1 } } : undefined }
    clearSelection() { this.selection = '' }
    focus() {}
    dispose() { this.disposed = true }
  }
  return { Terminal }
})
vi.mock('@xterm/addon-fit', () => ({ FitAddon: class { fit() { fake.fits += 1 } } }))
vi.mock('@xterm/xterm/css/xterm.css', () => ({}))

import TerminalPane from '../TerminalPane.vue'
import { useTerminalStore } from '../../../stores/terminal'

enableAutoUnmount(afterEach)
let pinia: Pinia

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  fake.instances.length = 0
  fake.fits = 0
  fake.holdWrites = false
  fake.observers.length = 0
  vi.stubGlobal('ResizeObserver', class {
    constructor(cb: () => void) { fake.observers.push(cb) }
    observe() {}
    disconnect() {}
  })
})
afterEach(() => vi.unstubAllGlobals())

function setup(session: Partial<{ connected: boolean; busy: boolean; exited: boolean; closed: boolean; closeCode: number | null; buffer: string }> = {}) {
  const store = useTerminalStore(pinia)
  store.sessions = { s1: { connected: false, busy: false, exited: false, closed: false, closeCode: null, buffer: '', ...session } }
  const connect = vi.spyOn(store, 'connect').mockImplementation(() => {})
  const disconnect = vi.spyOn(store, 'disconnect').mockImplementation(() => {})
  const sendInput = vi.spyOn(store, 'sendInput').mockImplementation(() => {})
  const resize = vi.spyOn(store, 'resize').mockImplementation(() => {})
  const attach = vi.spyOn(store, 'attach').mockImplementation(() => {})
  const close = vi.spyOn(store, 'close').mockResolvedValue(undefined)
  let output: (data: string, reset: boolean) => void = () => {}
  const unsubscribe = vi.fn()
  vi.spyOn(store, 'onOutput').mockImplementation((_id, cb) => { output = cb; return unsubscribe })
  const wrapper = mount(TerminalPane, { props: { sessionId: 's1' }, global: { plugins: [pinia] } })
  return { wrapper, store, connect, disconnect, sendInput, resize, attach, close, unsubscribe, emit: (d: string, r = false) => output(d, r) }
}

const term = () => fake.instances[0] as Record<string, any>

describe('terminal da sessão', () => {
  it('ao montar, conecta, abre o xterm e escreve o buffer atual', async () => {
    const { wrapper, connect } = setup({ buffer: 'olá\r\n' })
    await flushPromises()

    expect(connect).toHaveBeenCalledWith('s1', false)
    expect(fake.instances).toHaveLength(1)
    expect(term().opened).toBe(wrapper.get('[data-test="terminal-screen"]').element)
    expect(term().written).toEqual(['olá\r\n'])
    expect(term().options.fontFamily).toContain('JetBrains Mono')
    expect(fake.fits).toBeGreaterThan(0)
  })

  it('não escreve nada quando o buffer está vazio', () => {
    setup()
    expect(term().written).toEqual([])
  })

  it('escreve a saída nova e limpa a tela antes de um replay', () => {
    const { emit } = setup()
    emit('um')
    emit('dois')
    expect(term().resets).toBe(0)
    expect(term().written).toEqual(['um', 'dois'])

    emit('replay', true)
    expect(term().resets).toBe(1)
    expect(term().written).toEqual(['replay'])
  })

  it('manda o que se digita para o terminal', () => {
    const { sendInput } = setup()
    term().dataCb!('ls\r')
    expect(sendInput).toHaveBeenCalledWith('s1', 'ls\r')
  })

  it('ajusta o tamanho e avisa o servidor quando o painel muda', () => {
    const { resize } = setup()
    expect(resize).toHaveBeenCalledWith('s1', 80, 3)
    resize.mockClear()
    const fitsBefore = fake.fits

    fake.observers.forEach((cb) => cb())
    expect(fake.fits).toBeGreaterThan(fitsBefore)
    expect(resize).not.toHaveBeenCalled() // same size: nothing to say

    term().cols = 100
    fake.observers.forEach((cb) => cb())
    expect(resize).toHaveBeenCalledWith('s1', 100, 3)
  })

  it('Anexar tela manda as linhas visíveis sem espaços no fim', async () => {
    const { wrapper, attach } = setup()
    await wrapper.get('[data-test="terminal-attach-screen"]').trigger('click')
    expect(attach).toHaveBeenCalledWith('s1', '$ ls\na.txt')
  })

  it('com seleção, mostra Anexar à mensagem; o clique anexa o trecho e limpa a seleção', async () => {
    const { wrapper, attach } = setup()
    expect(wrapper.find('[data-test="terminal-attach-selection"]').exists()).toBe(false)

    term().selection = 'a.txt'
    term().selectionCb!()
    await flushPromises()
    const button = wrapper.get('[data-test="terminal-attach-selection"]')
    expect(button.text()).toBe('Anexar à mensagem')

    await button.trigger('click')
    expect(attach).toHaveBeenCalledWith('s1', 'a.txt')
    expect(term().selection).toBe('')
    expect(wrapper.find('[data-test="terminal-attach-selection"]').exists()).toBe(false)
  })

  it('esconde o botão quando a seleção some', async () => {
    const { wrapper } = setup()
    term().selection = 'x'
    term().selectionCb!()
    await flushPromises()
    term().selection = ''
    term().selectionCb!()
    await flushPromises()
    expect(wrapper.find('[data-test="terminal-attach-selection"]').exists()).toBe(false)
  })

  it('Encerrar chama o fechamento do terminal', async () => {
    const { wrapper, close } = setup()
    await wrapper.get('[data-test="terminal-close"]').trigger('click')
    expect(close).toHaveBeenCalledWith('s1')
  })

  it('mostra o erro quando não consegue encerrar', async () => {
    const { wrapper, close } = setup()
    close.mockRejectedValueOnce(new Error('falhou'))
    await wrapper.get('[data-test="terminal-close"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-test="terminal-error"]').text()).toContain('falhou')
  })

  it('não mostra o aviso de fim enquanto o terminal está aberto', () => {
    const { wrapper } = setup({ connected: true })
    expect(wrapper.find('[data-test="terminal-ended"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="terminal-reopen"]').exists()).toBe(false)
  })

  it('com o shell encerrado, mostra o aviso e Abrir de novo, que conecta outra vez', async () => {
    const { wrapper, store, connect, disconnect } = setup({ connected: true })
    store.sessions = { s1: { ...store.sessions.s1, exited: true } }
    await flushPromises()

    expect(wrapper.get('[data-test="terminal-ended"]').text()).toContain('O terminal foi encerrado.')
    connect.mockClear()
    await wrapper.get('[data-test="terminal-reopen"]').trigger('click')
    expect(disconnect).toHaveBeenCalledWith('s1')
    expect(connect).toHaveBeenCalledWith('s1', true)
  })

  it('com o socket fechado, mesmo sem nunca ter conectado, mostra o aviso e Abrir de novo', async () => {
    const { wrapper, store } = setup()
    expect(wrapper.find('[data-test="terminal-ended"]').exists()).toBe(false)
    store.sessions = { s1: { ...store.sessions.s1, closed: true, closeCode: 4500 } }
    await flushPromises()
    expect(wrapper.get('[data-test="terminal-ended"]').text()).toContain('O terminal foi encerrado.')
    expect(wrapper.find('[data-test="terminal-reopen"]').exists()).toBe(true)
  })

  it('o código 4409 troca o texto pelo da pasta que não existe mais', async () => {
    const { wrapper } = setup({ closed: true, closeCode: 4409 })
    const ended = wrapper.get('[data-test="terminal-ended"]')
    expect(ended.text()).toContain('A pasta da sessão não existe mais.')
    expect(ended.text()).not.toContain('O terminal foi encerrado.')
    expect(wrapper.find('[data-test="terminal-reopen"]').exists()).toBe(true)
  })

  it('Abrir de novo não precisa reenviar o tamanho: a store o manda a cada conexão nova', async () => {
    const { wrapper, resize } = setup({ exited: true })
    expect(resize).toHaveBeenCalledTimes(1)
    await wrapper.get('[data-test="terminal-reopen"]').trigger('click')
    expect(resize).toHaveBeenCalledTimes(1)
  })

  it('montar por um gesto (aba, botão do cabeçalho, play) conecta pedindo para abrir; sem gesto só liga', () => {
    const store = useTerminalStore(pinia)
    store.openPanel('s1')
    const { connect } = setup()
    expect(connect).toHaveBeenCalledWith('s1', true)
  })

  it('com o close 4410 mostra o estado vazio com Abrir terminal, sem a mensagem de encerrado', async () => {
    const { wrapper } = setup({ closed: true, closeCode: 4410 })
    const empty = wrapper.get('[data-test="terminal-empty"]')
    expect(empty.text()).toContain('Nenhum terminal aberto nesta sessão.')
    expect(empty.get('[data-test="terminal-open"]').text()).toBe('Abrir terminal')
    expect(wrapper.find('[data-test="terminal-ended"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('O terminal foi encerrado.')
  })

  it('o estado vazio some quando há terminal e não aparece sem o 4410', async () => {
    const { wrapper, store } = setup({ closed: true, closeCode: 4410 })
    expect(wrapper.find('[data-test="terminal-empty"]').exists()).toBe(true)
    store.sessions = { s1: { ...store.sessions.s1, closed: false, closeCode: null, connected: true } }
    await flushPromises()
    expect(wrapper.find('[data-test="terminal-empty"]').exists()).toBe(false)
    store.sessions = { s1: { ...store.sessions.s1, closed: true, closeCode: 4500, connected: false } }
    await flushPromises()
    expect(wrapper.find('[data-test="terminal-empty"]').exists()).toBe(false)
  })

  it('Abrir terminal reconecta no modo abrir', async () => {
    const { wrapper, connect, disconnect } = setup({ closed: true, closeCode: 4410 })
    connect.mockClear()
    await wrapper.get('[data-test="terminal-open"]').trigger('click')
    expect(disconnect).toHaveBeenCalledWith('s1')
    expect(connect).toHaveBeenCalledWith('s1', true)
  })

  it('um pedido do terminal (cabeçalho, play) com o painel já montado e sem terminal reconecta abrindo', async () => {
    const { store, connect } = setup({ closed: true, closeCode: 4410 })
    connect.mockClear()
    store.openPanel('s1')
    await flushPromises()
    expect(connect).toHaveBeenCalledWith('s1', true)
  })

  it('um pedido do terminal enquanto o socket que só liga ainda conecta pede connect abrindo (a store troca o socket)', async () => {
    const { store, connect, disconnect } = setup()
    connect.mockClear()
    store.openPanel('s1')
    await flushPromises()
    expect(connect).toHaveBeenCalledWith('s1', true)
    expect(disconnect).not.toHaveBeenCalled()
  })

  it('um pedido do terminal com o terminal vivo não derruba a conexão', async () => {
    const { store, disconnect } = setup({ connected: true })
    store.openPanel('s1')
    await flushPromises()
    expect(disconnect).not.toHaveBeenCalled()
  })

  it('um pedido para outra sessão não mexe neste terminal', async () => {
    const { store, connect } = setup({ closed: true, closeCode: 4410 })
    connect.mockClear()
    store.openPanel('outra')
    await flushPromises()
    expect(connect).not.toHaveBeenCalled()
  })

  it('o que o xterm responde ao reescrever o replay (CSI c, CSI 6n) não vai ao shell', () => {
    const { emit, sendInput } = setup()
    term().hold = true
    term().onWrite = (data: string) => { if (data.includes('\x1b[c')) term().dataCb!('\x1b[?1;2c') }
    emit('antigo \x1b[c \x1b[6n', true)
    expect(sendInput).not.toHaveBeenCalled()

    // Typing is ignored until the replay is written; afterwards it flows again.
    term().dataCb!('x')
    expect(sendInput).not.toHaveBeenCalled()
    term().flush()
    term().dataCb!('y')
    expect(sendInput).toHaveBeenCalledWith('s1', 'y')
  })

  it('o buffer escrito na montagem também não gera respostas fantasmas', () => {
    fake.holdWrites = true
    const { sendInput } = setup({ buffer: 'a\x1b[c' })
    term().dataCb!('\x1b[?1;2c')
    expect(sendInput).not.toHaveBeenCalled()
    term().flush()
    term().dataCb!('z')
    expect(sendInput).toHaveBeenCalledWith('s1', 'z')
  })

  it('mostra o aviso na montagem quando o shell já tinha saído', () => {
    const { wrapper } = setup({ exited: true })
    expect(wrapper.find('[data-test="terminal-ended"]').exists()).toBe(true)
  })

  it('desmontar descarta o xterm e a assinatura, mas não desconecta', () => {
    const { wrapper, disconnect, unsubscribe } = setup()
    wrapper.unmount()
    expect(term().disposed).toBe(true)
    expect(unsubscribe).toHaveBeenCalled()
    expect(disconnect).not.toHaveBeenCalled()
  })
})
