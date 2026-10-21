import { beforeEach, describe, expect, it, vi } from 'vitest'
import { TerminalSocket, type TerminalFrame } from '../terminalSocket'

class FakeSocket {
  onopen: ((ev: unknown) => void) | null = null
  onclose: ((ev: unknown) => void) | null = null
  onerror: ((ev: unknown) => void) | null = null
  onmessage: ((ev: { data: unknown }) => void) | null = null
  sent: string[] = []
  closed = false
  readyState = 1
  url: string

  constructor(url: string) {
    this.url = url
  }

  send(data: string) {
    this.sent.push(data)
  }

  emit(frame: object) {
    this.onmessage?.({ data: JSON.stringify(frame) })
  }

  close() {
    this.closed = true
  }
}

let sockets: FakeSocket[]

function build(sessionId = 's1', open = false) {
  return new TerminalSocket(sessionId, open, (url) => {
    const socket = new FakeSocket(url)
    sockets.push(socket)
    return socket
  })
}

beforeEach(() => {
  sockets = []
})

describe('TerminalSocket', () => {
  it('monta a URL com o host da página e o id da sessão escapado', () => {
    build('a b/c')
    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
    expect(sockets[0]!.url).toBe(`${protocol}://${window.location.host}/ws/terminal/${encodeURIComponent('a b/c')}`)
  })

  it('só pede para abrir o shell quando open é verdadeiro (?open=1)', () => {
    build('s1')
    build('s1', true)
    expect(sockets[0]!.url).not.toContain('?')
    expect(sockets[1]!.url.endsWith('/ws/terminal/s1?open=1')).toBe(true)
  })

  it('repassa os frames JSON a quem assinou e para de repassar depois de cancelar', () => {
    const terminal = build()
    const got: TerminalFrame[] = []
    const off = terminal.onFrame((frame) => got.push(frame))
    sockets[0]!.emit({ type: 'replay', data: 'oi', cols: 80, rows: 24 })
    sockets[0]!.emit({ type: 'output', data: 'x' })
    sockets[0]!.emit({ type: 'busy', busy: true })
    sockets[0]!.emit({ type: 'run', run_id: 'r1', state: 'sent', exit_code: 0 })
    sockets[0]!.emit({ type: 'exit' })
    expect(got.map((f) => f.type)).toEqual(['replay', 'output', 'busy', 'run', 'exit'])
    expect(got[3]).toEqual({ type: 'run', run_id: 'r1', state: 'sent', exit_code: 0 })
    off()
    sockets[0]!.emit({ type: 'output', data: 'y' })
    expect(got).toHaveLength(5)
  })

  it('ignora lixo: texto que não é JSON, tipo desconhecido e valores soltos', () => {
    const terminal = build()
    const cb = vi.fn()
    terminal.onFrame(cb)
    sockets[0]!.onmessage?.({ data: 'não é json' })
    sockets[0]!.onmessage?.({ data: '42' })
    sockets[0]!.emit({ type: 'desconhecido' })
    expect(cb).not.toHaveBeenCalled()
  })

  it('sendInput e resize enviam o JSON do contrato', () => {
    const terminal = build()
    terminal.sendInput('ls\r')
    terminal.resize(100, 30)
    expect(sockets[0]!.sent.map((s) => JSON.parse(s))).toEqual([
      { type: 'input', data: 'ls\r' },
      { type: 'resize', cols: 100, rows: 30 },
    ])
  })

  it('guarda o que se envia enquanto conecta e despeja na abertura, na ordem', () => {
    const terminal = build()
    sockets[0]!.readyState = 0
    terminal.resize(90, 20)
    terminal.sendInput('a')
    expect(sockets[0]!.sent).toEqual([])
    sockets[0]!.readyState = 1
    sockets[0]!.onopen?.({})
    expect(sockets[0]!.sent.map((s) => JSON.parse(s))).toEqual([
      { type: 'resize', cols: 90, rows: 20 },
      { type: 'input', data: 'a' },
    ])
  })

  it('onClose recebe o código e não reconecta sozinho', () => {
    const terminal = build()
    const codes: number[] = []
    const off = terminal.onClose((code) => codes.push(code))
    sockets[0]!.onclose?.({ code: 4409 })
    expect(codes).toEqual([4409])
    expect(sockets).toHaveLength(1)
    off()
    sockets[0]!.onclose?.({ code: 1000 })
    expect(codes).toEqual([4409])
  })

  it('close() fecha o socket e depois disso nada mais é enviado', () => {
    const terminal = build()
    terminal.close()
    expect(sockets[0]!.closed).toBe(true)
    terminal.sendInput('x')
    expect(sockets[0]!.sent).toEqual([])
  })
})
