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
    open: boolean
    frameCbs = new Set<(f: unknown) => void>()
    closeCbs = new Set<(code: number) => void>()
    sentInput: string[] = []
    sizes: Array<[number, number]> = []
    closed = false
    constructor(sessionId: string, open = false) {
      this.sessionId = sessionId
      this.open = open
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
  open: boolean
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

  it('connect só liga por padrão e abre o shell (open) quando pedido', () => {
    const store = useTerminalStore()
    store.connect('s1')
    store.connect('s2', true)
    expect(sockets().map((s) => s.open)).toEqual([false, true])
  })

  it('um pedido de abrir troca o socket que só liga e ainda não conectou; um já conectado fica', () => {
    const store = useTerminalStore()
    store.connect('s1')
    store.connect('s1', true)
    expect(sockets()).toHaveLength(2)
    expect(sockets()[0]!.closed).toBe(true)
    expect(sockets()[1]!.open).toBe(true)

    store.connect('s2')
    sockets()[2]!.emit({ type: 'replay', data: '', cols: 80, rows: 24, runs: [] })
    store.connect('s2', true)
    expect(sockets()).toHaveLength(3)
  })

  it('o close 4410 marca closed com o código e não é erro', () => {
    const store = useTerminalStore()
    store.connect('s1')
    sockets()[0]!.drop(4410)
    expect(store.sessions.s1).toMatchObject({ connected: false, closed: true, closeCode: 4410, exited: false })
  })

  it('o pedido de abrir (openPanel) vale uma vez para o painel que monta', () => {
    const store = useTerminalStore()
    expect(store.takeOpenRequest('s1')).toBe(false)
    store.openPanel('s1')
    expect(store.takeOpenRequest('s1')).toBe(true)
    expect(store.takeOpenRequest('s1')).toBe(false)
    store.requestOpen('s2')
    store.disconnect('s2')
    expect(store.takeOpenRequest('s2')).toBe(false)
  })

  it('a cada nova conexão o último tamanho conhecido vai ao novo socket', () => {
    const store = useTerminalStore()
    store.connect('s1')
    store.resize('s1', 100, 30)
    store.disconnect('s1')
    store.connect('s1', true)
    expect(sockets()[1]!.sizes).toEqual([[100, 30]])
    store.connect('s2')
    expect(sockets()[2]!.sizes).toEqual([])
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

  it('um fechamento antes de abrir marca closed com o código, e connect zera', () => {
    const store = useTerminalStore()
    store.connect('s1')
    expect(store.sessions.s1).toMatchObject({ closed: false, closeCode: null })
    sockets()[0]!.drop(4409)
    expect(store.sessions.s1).toMatchObject({ connected: false, closed: true, closeCode: 4409 })

    store.connect('s1')
    expect(store.sessions.s1).toMatchObject({ closed: false, closeCode: null })
    sockets()[1]!.drop(1006)
    expect(store.sessions.s1).toMatchObject({ closed: true, closeCode: 1006 })
  })

  it('disconnect não conta como fechamento e o fechamento tardio do socket antigo é ignorado', () => {
    const store = useTerminalStore()
    store.connect('s1')
    store.disconnect('s1')
    expect(store.sessions.s1).toMatchObject({ closed: false, closeCode: null })
    sockets()[0]!.drop(1000)
    expect(store.sessions.s1).toMatchObject({ closed: false, closeCode: null })
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
  it('abre o painel, conecta e chama o POST; o run fica running assim que o POST responde', async () => {
    vi.mocked(runInTerminal).mockResolvedValue({ run_id: 'r1' })
    const store = useTerminalStore()
    await store.run('s1', 'ls', 'blk')
    expect(runInTerminal).toHaveBeenCalledWith('s1', 'ls')
    expect(store.panelRequest).toMatchObject({ sessionId: 's1' })
    expect(sockets()).toHaveLength(1)
    expect(store.runStateFor('blk')).toBe('running')
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
    expect(store.runs.blk).toMatchObject({ state: 'running', exitCode: null })
    // O frame antigo, repetido, não mexe no run novo.
    sockets()[0]!.emit({ type: 'run', run_id: 'r1', state: 'failed', exit_code: 1 })
    expect(store.runStateFor('blk')).toBe('running')
  })

  it('um clique repetido enquanto o bloco roda não dispara outro POST', async () => {
    vi.mocked(runInTerminal).mockResolvedValue({ run_id: 'r1' })
    const store = useTerminalStore()
    await store.run('s1', 'ls', 'blk')
    await store.run('s1', 'ls', 'blk')
    expect(runInTerminal).toHaveBeenCalledTimes(1)
  })
})

describe('run e o estado do servidor', () => {
  async function startRun(store: ReturnType<typeof useTerminalStore>, runId = 'r1', block = 'blk') {
    vi.mocked(runInTerminal).mockResolvedValueOnce({ run_id: runId })
    await store.run('s1', 'sleep 9', block)
    sockets()[sockets().length - 1]!.emit({ type: 'run', run_id: runId, state: 'running', exit_code: null })
  }

  it('o play abre o shell: connect com open', async () => {
    vi.mocked(runInTerminal).mockResolvedValue({ run_id: 'r1' })
    await useTerminalStore().run('s1', 'ls', 'blk')
    expect(sockets()[0]!.open).toBe(true)
  })

  it('desconecta e volta com um replay que traz o run como sent: sai de running', async () => {
    const store = useTerminalStore()
    await startRun(store)
    expect(store.runStateFor('blk')).toBe('running')
    store.disconnect('s1')
    store.connect('s1')
    sockets()[1]!.emit({ type: 'replay', data: '', cols: 80, rows: 24, runs: [{ run_id: 'r1', state: 'sent', exit_code: 0 }] })
    expect(store.runs.blk).toMatchObject({ state: 'sent', exitCode: 0 })
  })

  it('o replay que ainda traz o run como running mantém running', async () => {
    const store = useTerminalStore()
    await startRun(store)
    store.disconnect('s1')
    store.connect('s1')
    sockets()[1]!.emit({ type: 'replay', data: '', cols: 80, rows: 24, runs: [{ run_id: 'r1', state: 'running', exit_code: null }] })
    expect(store.runStateFor('blk')).toBe('running')
  })

  it('um replay sem o run o marca como interrupted', async () => {
    const store = useTerminalStore()
    await startRun(store)
    store.disconnect('s1')
    store.connect('s1')
    sockets()[1]!.emit({ type: 'replay', data: '', cols: 80, rows: 24, runs: [] })
    expect(store.runStateFor('blk')).toBe('interrupted')
  })

  it('um replay sem a lista de runs não mexe nos runs', async () => {
    const store = useTerminalStore()
    await startRun(store)
    sockets()[0]!.emit({ type: 'replay', data: '', cols: 80, rows: 24 })
    expect(store.runStateFor('blk')).toBe('running')
  })

  it('o replay não muda um run starting nem o run de outra sessão', async () => {
    let resolve!: (value: { run_id: string }) => void
    vi.mocked(runInTerminal).mockReturnValueOnce(new Promise((r) => { resolve = r }))
    const store = useTerminalStore()
    const pending = store.run('s1', 'ls', 'blk')
    sockets()[0]!.emit({ type: 'replay', data: '', cols: 80, rows: 24, runs: [] })
    expect(store.runStateFor('blk')).toBe('starting')
    resolve({ run_id: 'r1' })
    await pending

    vi.mocked(runInTerminal).mockResolvedValueOnce({ run_id: 'r2' })
    await store.run('s2', 'ls', 'other')
    sockets()[1]!.emit({ type: 'run', run_id: 'r2', state: 'running', exit_code: null })
    sockets()[0]!.emit({ type: 'replay', data: '', cols: 80, rows: 24, runs: [] })
    expect(store.runStateFor('other')).toBe('running')
  })

  it('o frame exit marca os runs running da sessão como interrupted', async () => {
    const store = useTerminalStore()
    await startRun(store)
    sockets()[0]!.emit({ type: 'exit' })
    expect(store.runStateFor('blk')).toBe('interrupted')
  })

  it('o close 4410 também solta os runs running da sessão', async () => {
    const store = useTerminalStore()
    await startRun(store)
    sockets()[0]!.drop(4410)
    expect(store.runStateFor('blk')).toBe('interrupted')
  })

  it('depois de interrupted, um novo run chama o POST outra vez', async () => {
    const store = useTerminalStore()
    await startRun(store)
    sockets()[0]!.emit({ type: 'exit' })
    vi.mocked(runInTerminal).mockResolvedValueOnce({ run_id: 'r2' })
    await store.run('s1', 'sleep 9', 'blk')
    expect(runInTerminal).toHaveBeenCalledTimes(2)
    expect(store.runStateFor('blk')).toBe('running')
  })

  it('o clique repetido enquanto está running continua recusado', async () => {
    const store = useTerminalStore()
    await startRun(store)
    await store.run('s1', 'sleep 9', 'blk')
    expect(runInTerminal).toHaveBeenCalledTimes(1)
  })

  it('o POST que responde com um run_id que o replay já trouxe terminado adota esse estado', async () => {
    let resolve!: (value: { run_id: string }) => void
    vi.mocked(runInTerminal).mockReturnValueOnce(new Promise((r) => { resolve = r }))
    const store = useTerminalStore()
    const pending = store.run('s1', 'ls', 'blk')
    sockets()[0]!.emit({ type: 'replay', data: '', cols: 80, rows: 24, runs: [{ run_id: 'r1', state: 'sent', exit_code: 0 }] })
    expect(store.runStateFor('blk')).toBe('starting')
    resolve({ run_id: 'r1' })
    await pending
    expect(store.runs.blk).toMatchObject({ state: 'sent', exitCode: 0 })
  })

  it('o POST que responde depois de o socket cair (sem o frame running) deixa o run em running, e o replay o resolve', async () => {
    let resolve!: (value: { run_id: string }) => void
    vi.mocked(runInTerminal).mockReturnValueOnce(new Promise((r) => { resolve = r }))
    const store = useTerminalStore()
    const pending = store.run('s1', 'pnpm test', 'blk')
    expect(store.runStateFor('blk')).toBe('starting')
    store.disconnect('s1')
    resolve({ run_id: 'r1' })
    await pending
    expect(store.runStateFor('blk')).toBe('running')

    store.connect('s1')
    sockets()[1]!.emit({ type: 'replay', data: '', cols: 80, rows: 24, runs: [{ run_id: 'r1', state: 'sent', exit_code: 0 }] })
    expect(store.runs.blk).toMatchObject({ state: 'sent', exitCode: 0 })
    vi.mocked(runInTerminal).mockResolvedValueOnce({ run_id: 'r2' })
    await store.run('s1', 'pnpm test', 'blk')
    expect(runInTerminal).toHaveBeenCalledTimes(2)
  })

  it('o POST que responde depois de o socket cair e o replay não o conhece: vira interrupted', async () => {
    let resolve!: (value: { run_id: string }) => void
    vi.mocked(runInTerminal).mockReturnValueOnce(new Promise((r) => { resolve = r }))
    const store = useTerminalStore()
    const pending = store.run('s1', 'x', 'blk')
    store.disconnect('s1')
    resolve({ run_id: 'r1' })
    await pending
    store.connect('s1')
    sockets()[1]!.emit({ type: 'replay', data: '', cols: 80, rows: 24, runs: [] })
    expect(store.runStateFor('blk')).toBe('interrupted')
  })

  it('o replay corrige um run marcado interrupted por engano com o estado que o servidor tem', async () => {
    const store = useTerminalStore()
    await startRun(store)
    sockets()[0]!.emit({ type: 'exit' })
    expect(store.runStateFor('blk')).toBe('interrupted')
    store.disconnect('s1')
    store.connect('s1')
    sockets()[1]!.emit({ type: 'replay', data: '', cols: 80, rows: 24, runs: [{ run_id: 'r1', state: 'sent', exit_code: 0 }] })
    expect(store.runs.blk).toMatchObject({ state: 'sent', exitCode: 0 })
  })

  it('o replay não mexe em run interrupted que ele não conhece', async () => {
    const store = useTerminalStore()
    await startRun(store)
    sockets()[0]!.emit({ type: 'exit' })
    store.disconnect('s1')
    store.connect('s1')
    sockets()[1]!.emit({ type: 'replay', data: '', cols: 80, rows: 24, runs: [] })
    expect(store.runs.blk).toMatchObject({ state: 'interrupted' })
  })

  it('409 mostra o detail da resposta: ocupado vira busy, pasta ausente vira failed com o texto', async () => {
    const store = useTerminalStore()
    vi.mocked(runInTerminal).mockRejectedValueOnce(new ApiError(409, 'O terminal está ocupado.', 'Falhou'))
    await store.run('s1', 'ls', 'a')
    expect(store.runStateFor('a')).toBe('busy')

    vi.mocked(runInTerminal).mockRejectedValueOnce(new ApiError(409, 'A pasta da sessão não existe mais.', 'Falhou'))
    await store.run('s1', 'ls', 'b')
    expect(store.runs.b).toMatchObject({ state: 'failed', message: 'A pasta da sessão não existe mais.' })
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
