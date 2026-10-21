import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../../api/http', async (orig) => ({
  ...(await orig<typeof import('../../api/http')>()),
  runInTerminal: vi.fn(),
  closeTerminal: vi.fn(),
}))

vi.mock('../../api/terminalSocket', () => {
  class TerminalSocket {
    static instances: TerminalSocket[] = []
    sessionId: string
    frameCbs = new Set<(f: unknown) => void>()
    closeCbs = new Set<(code: number) => void>()
    sentInput: string[] = []
    sizes: Array<[number, number]> = []
    closed = false
    constructor(sessionId: string) {
      this.sessionId = sessionId
      TerminalSocket.instances.push(this)
    }
    onFrame(cb: (f: unknown) => void) {
      this.frameCbs.add(cb)
      return () => this.frameCbs.delete(cb)
    }
    onClose(cb: (code: number) => void) {
      this.closeCbs.add(cb)
      return () => this.closeCbs.delete(cb)
    }
    sendInput(data: string) {
      this.sentInput.push(data)
    }
    resize(cols: number, rows: number) {
      this.sizes.push([cols, rows])
    }
    close() {
      this.closed = true
    }
    emit(frame: unknown) {
      this.frameCbs.forEach((cb) => cb(frame))
    }
    drop(code = 1006) {
      this.closeCbs.forEach((cb) => cb(code))
    }
  }
  return { TerminalSocket }
})

import { ApiError, closeTerminal, runInTerminal } from '../../api/http'
import { TerminalSocket } from '../../api/terminalSocket'
import { useTerminalStore } from '../terminal'

interface FakeTerminalSocket {
  emit(frame: unknown): void
  drop(code?: number): void
  sentInput: string[]
  sizes: Array<[number, number]>
  closed: boolean
}

function sockets(): FakeTerminalSocket[] {
  return (TerminalSocket as unknown as { instances: FakeTerminalSocket[] }).instances
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.resetAllMocks()
  sockets().length = 0
})

afterEach(() => vi.useRealTimers())

describe('conexão', () => {
  it('connect é idempotente e marca conectado no primeiro frame', () => {
    const store = useTerminalStore()
    store.connect('s1')
    store.connect('s1')
    expect(sockets()).toHaveLength(1)
    expect(store.sessions.s1).toMatchObject({ connected: false, busy: false, exited: false, buffer: '' })
    sockets()[0]!.emit({ type: 'replay', data: 'oi', cols: 80, rows: 24 })
    expect(store.sessions.s1).toMatchObject({ connected: true, buffer: 'oi' })
  })

  it('output soma ao buffer, replay substitui, busy e exit atualizam o estado', () => {
    const store = useTerminalStore()
    store.connect('s1')
    const socket = sockets()[0]!
    socket.emit({ type: 'replay', data: 'a', cols: 80, rows: 24 })
    socket.emit({ type: 'output', data: 'b' })
    expect(store.sessions.s1!.buffer).toBe('ab')
    socket.emit({ type: 'busy', busy: true })
    expect(store.sessions.s1!.busy).toBe(true)
    socket.emit({ type: 'exit' })
    expect(store.sessions.s1).toMatchObject({ exited: true, busy: false })
    socket.emit({ type: 'replay', data: 'z', cols: 80, rows: 24 })
    expect(store.sessions.s1!.buffer).toBe('z')
  })

  it('o buffer é cortado em 262 144 caracteres, mantendo o fim', () => {
    const store = useTerminalStore()
    store.connect('s1')
    const socket = sockets()[0]!
    socket.emit({ type: 'replay', data: 'x'.repeat(262_000), cols: 80, rows: 24 })
    socket.emit({ type: 'output', data: 'y'.repeat(1000) })
    const buffer = store.sessions.s1!.buffer
    expect(buffer).toHaveLength(262_144)
    expect(buffer.endsWith('y'.repeat(1000))).toBe(true)
    socket.emit({ type: 'replay', data: 'r'.repeat(300_000), cols: 80, rows: 24 })
    expect(store.sessions.s1!.buffer).toHaveLength(262_144)
  })

  it('onOutput recebe a saída nova e o replay (com reset), e para ao cancelar', () => {
    const store = useTerminalStore()
    store.connect('s1')
    const cb = vi.fn()
    const off = store.onOutput('s1', cb)
    sockets()[0]!.emit({ type: 'replay', data: 'a', cols: 80, rows: 24 })
    sockets()[0]!.emit({ type: 'output', data: 'b' })
    expect(cb.mock.calls).toEqual([['a', true], ['b', false]])
    off()
    sockets()[0]!.emit({ type: 'output', data: 'c' })
    expect(cb).toHaveBeenCalledTimes(2)
  })

  it('o fechamento marca desconectado e connect abre outro socket', () => {
    const store = useTerminalStore()
    store.connect('s1')
    sockets()[0]!.emit({ type: 'replay', data: '', cols: 80, rows: 24 })
    sockets()[0]!.drop(1006)
    expect(store.sessions.s1).toMatchObject({ connected: false, busy: false })
    store.connect('s1')
    expect(sockets()).toHaveLength(2)
    expect(store.sessions.s1!.exited).toBe(false)
  })

  it('disconnect fecha o socket e um fechamento tardio dele não mexe no estado novo', () => {
    const store = useTerminalStore()
    store.connect('s1')
    const first = sockets()[0]!
    first.emit({ type: 'replay', data: 'a', cols: 80, rows: 24 })
    store.disconnect('s1')
    expect(first.closed).toBe(true)
    expect(store.sessions.s1!.connected).toBe(false)
    store.connect('s1')
    sockets()[1]!.emit({ type: 'replay', data: 'b', cols: 80, rows: 24 })
    first.drop(1000)
    expect(store.sessions.s1).toMatchObject({ connected: true, buffer: 'b' })
  })

  it('sendInput e resize vão ao socket da sessão', () => {
    const store = useTerminalStore()
    store.connect('s1')
    store.sendInput('s1', 'ls\r')
    store.resize('s1', 100, 30)
    store.sendInput('s2', 'ignorado')
    expect(sockets()[0]!.sentInput).toEqual(['ls\r'])
    expect(sockets()[0]!.sizes).toEqual([[100, 30]])
  })

  it('openPanel incrementa o seq a cada pedido', () => {
    const store = useTerminalStore()
    expect(store.panelRequest).toBeNull()
    store.openPanel('s1')
    expect(store.panelRequest).toEqual({ sessionId: 's1', seq: 1 })
    store.openPanel('s1')
    expect(store.panelRequest).toEqual({ sessionId: 's1', seq: 2 })
  })

  it('close chama DELETE do terminal', async () => {
    vi.mocked(closeTerminal).mockResolvedValue(undefined)
    await useTerminalStore().close('s1')
    expect(closeTerminal).toHaveBeenCalledWith('s1')
  })
})

describe('run', () => {
  it('abre o painel, conecta e chama o POST; o run fica starting até o frame', async () => {
    vi.mocked(runInTerminal).mockResolvedValue({ run_id: 'r1' })
    const store = useTerminalStore()
    await store.run('s1', 'ls', 'blk')
    expect(runInTerminal).toHaveBeenCalledWith('s1', 'ls')
    expect(store.panelRequest).toMatchObject({ sessionId: 's1' })
    expect(sockets()).toHaveLength(1)
    expect(store.runStateFor('blk')).toBe('starting')
    sockets()[0]!.emit({ type: 'run', run_id: 'r1', state: 'running', exit_code: null })
    expect(store.runStateFor('blk')).toBe('running')
    sockets()[0]!.emit({ type: 'run', run_id: 'r1', state: 'sent', exit_code: 0 })
    expect(store.runStateFor('blk')).toBe('sent')
    expect(store.runs.blk).toMatchObject({ state: 'sent', exitCode: 0, blockKey: 'blk' })
  })

  it('interrupted e failed vêm do frame', async () => {
    vi.mocked(runInTerminal).mockResolvedValueOnce({ run_id: 'r1' }).mockResolvedValueOnce({ run_id: 'r2' })
    const store = useTerminalStore()
    await store.run('s1', 'sleep 9', 'a')
    await store.run('s1', 'x', 'b')
    sockets()[0]!.emit({ type: 'run', run_id: 'r1', state: 'interrupted', exit_code: 130 })
    sockets()[0]!.emit({ type: 'run', run_id: 'r2', state: 'failed', exit_code: null })
    expect(store.runs.a).toMatchObject({ state: 'interrupted', exitCode: 130 })
    expect(store.runs.b).toMatchObject({ state: 'failed', exitCode: null })
  })

  it('um frame que chega antes da resposta do POST também vale', async () => {
    let resolve!: (value: { run_id: string }) => void
    vi.mocked(runInTerminal).mockReturnValue(new Promise((r) => { resolve = r }))
    const store = useTerminalStore()
    const pending = store.run('s1', 'ls', 'blk')
    sockets()[0]!.emit({ type: 'run', run_id: 'r1', state: 'running', exit_code: null })
    sockets()[0]!.emit({ type: 'run', run_id: 'r1', state: 'sent', exit_code: 0 })
    resolve({ run_id: 'r1' })
    await pending
    expect(store.runStateFor('blk')).toBe('sent')
  })

  it('um frame de run desconhecido é ignorado', () => {
    const store = useTerminalStore()
    store.connect('s1')
    sockets()[0]!.emit({ type: 'run', run_id: 'nada', state: 'sent', exit_code: 0 })
    expect(store.runs).toEqual({})
  })

  it('o 409 vira busy e volta a ocioso, sem registro, depois de 2500 ms', async () => {
    vi.useFakeTimers()
    vi.mocked(runInTerminal).mockRejectedValue(new ApiError(409, 'O terminal está ocupado.', 'Falhou'))
    const store = useTerminalStore()
    await store.run('s1', 'ls', 'blk')
    expect(store.runStateFor('blk')).toBe('busy')
    vi.advanceTimersByTime(2499)
    expect(store.runStateFor('blk')).toBe('busy')
    vi.advanceTimersByTime(1)
    expect(store.runStateFor('blk')).toBe('idle')
    expect(store.runs.blk).toBeUndefined()
  })

  it('outros erros viram failed', async () => {
    vi.mocked(runInTerminal).mockRejectedValue(new ApiError(503, 'O terminal não abriu.', 'Falhou'))
    const store = useTerminalStore()
    await store.run('s1', 'ls', 'blk')
    expect(store.runStateFor('blk')).toBe('failed')
    vi.mocked(runInTerminal).mockRejectedValue(new Error('rede'))
    await store.run('s1', 'ls', 'blk2')
    expect(store.runStateFor('blk2')).toBe('failed')
  })

  it('um novo run no mesmo bloco depois de terminar começa do zero', async () => {
    vi.mocked(runInTerminal).mockResolvedValueOnce({ run_id: 'r1' }).mockResolvedValueOnce({ run_id: 'r2' })
    const store = useTerminalStore()
    await store.run('s1', 'ls', 'blk')
    sockets()[0]!.emit({ type: 'run', run_id: 'r1', state: 'sent', exit_code: 0 })
    await store.run('s1', 'ls', 'blk')
    expect(store.runs.blk).toMatchObject({ state: 'starting', exitCode: null })
    // O frame antigo, repetido, não mexe no run novo.
    sockets()[0]!.emit({ type: 'run', run_id: 'r1', state: 'failed', exit_code: 1 })
    expect(store.runStateFor('blk')).toBe('starting')
  })

  it('um clique repetido enquanto o bloco roda não dispara outro POST', async () => {
    vi.mocked(runInTerminal).mockResolvedValue({ run_id: 'r1' })
    const store = useTerminalStore()
    await store.run('s1', 'ls', 'blk')
    await store.run('s1', 'ls', 'blk')
    expect(runInTerminal).toHaveBeenCalledTimes(1)
  })
})

describe('anexos', () => {
  it('attach guarda o texto, ignora vazio, e takeAttachments devolve e limpa', () => {
    const store = useTerminalStore()
    store.attach('s1', 'linha 1\nlinha 2')
    store.attach('s1', '   \n')
    store.attach('s1', '')
    store.attach('s2', 'outra')
    expect(store.attachments.s1).toEqual(['linha 1\nlinha 2'])
    expect(store.takeAttachments('s1')).toEqual(['linha 1\nlinha 2'])
    expect(store.takeAttachments('s1')).toEqual([])
    expect(store.attachments.s1).toBeUndefined()
    expect(store.attachments.s2).toEqual(['outra'])
  })

  it('removeAttachment tira pelo índice', () => {
    const store = useTerminalStore()
    store.attach('s1', 'a')
    store.attach('s1', 'b')
    store.attach('s1', 'c')
    store.removeAttachment('s1', 1)
    expect(store.attachments.s1).toEqual(['a', 'c'])
    store.removeAttachment('s1', 0)
    store.removeAttachment('s1', 0)
    expect(store.attachments.s1 ?? []).toEqual([])
    store.removeAttachment('s1', 5)
  })
})
