import { describe, expect, it } from 'vitest'
import { formatDuration, formatTerminalAttachments, NOTE_TEXT, type NoteCode } from '../terminalText'

describe('formatTerminalAttachments', () => {
  it('gera um bloco por trecho, cita com "> " e põe o texto do usuário no fim', () => {
    expect(formatTerminalAttachments(['a\n\nb', 'c'], 'por quê?')).toBe(
      '<!-- attach: Terminal -->\n> a\n> \n> b\n\n<!-- attach: Terminal -->\n> c\n\npor quê?',
    )
  })

  it('sem texto devolve só os blocos', () => {
    expect(formatTerminalAttachments(['c'], '')).toBe('<!-- attach: Terminal -->\n> c')
    expect(formatTerminalAttachments(['c'], '   \n')).toBe('<!-- attach: Terminal -->\n> c')
  })

  it('sem trechos devolve o texto como está', () => {
    expect(formatTerminalAttachments([], 'olá')).toBe('olá')
  })

  it('normaliza o fim de linha CRLF', () => {
    expect(formatTerminalAttachments(['a\r\nb'], 'x')).toBe('<!-- attach: Terminal -->\n> a\n> b\n\nx')
  })
})

describe('NOTE_TEXT', () => {
  it('tem o texto em português dos cinco códigos', () => {
    const codes: NoteCode[] = ['truncated', 'cleared', 'input', 'shell-exit', 'empty']
    expect(Object.keys(NOTE_TEXT).sort()).toEqual([...codes].sort())
    expect(NOTE_TEXT.truncated).toBe('Saída anterior cortada; só o fim foi enviado.')
    expect(NOTE_TEXT.cleared).toBe('O comando limpou a tela; o que veio antes não foi enviado.')
    expect(NOTE_TEXT.input).toBe('Você digitou no terminal durante o comando; a saída depois disso não foi enviada.')
    expect(NOTE_TEXT['shell-exit']).toBe('O shell saiu antes de o comando terminar.')
    expect(NOTE_TEXT.empty).toBe('Sem saída.')
  })
})

describe('formatDuration', () => {
  it('usa ms abaixo de um segundo e uma casa decimal com vírgula acima', () => {
    expect(formatDuration(1897)).toBe('1,9 s')
    expect(formatDuration(320)).toBe('320 ms')
    expect(formatDuration(0)).toBe('0 ms')
    expect(formatDuration(999)).toBe('999 ms')
    expect(formatDuration(1000)).toBe('1,0 s')
    expect(formatDuration(65_000)).toBe('65,0 s')
  })
})
