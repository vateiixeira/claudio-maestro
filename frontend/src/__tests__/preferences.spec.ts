import { describe, expect, it } from 'vitest'
import { formatEditorCommand, parseEditorCommand } from '../preferences'

describe('comando do editor', () => {
  it('separa por espaços', () => {
    expect(parseEditorCommand('code')).toEqual(['code'])
    expect(parseEditorCommand('  code   --reuse-window ')).toEqual(['code', '--reuse-window'])
  })

  it('aceita aspas simples e duplas para partes com espaço', () => {
    expect(parseEditorCommand('"/opt/meu editor/bin" --wait')).toEqual(['/opt/meu editor/bin', '--wait'])
    expect(parseEditorCommand("subl '--name=a b'")).toEqual(['subl', '--name=a b'])
  })

  it('texto vazio dá lista vazia', () => {
    expect(parseEditorCommand('')).toEqual([])
    expect(parseEditorCommand('   ')).toEqual([])
  })

  it('aspas sem fechar dão erro legível', () => {
    expect(() => parseEditorCommand('code "abc')).toThrow('Aspas sem fechar.')
  })

  it('formata de volta, com aspas só quando precisa', () => {
    expect(formatEditorCommand(['code', '--reuse-window'])).toBe('code --reuse-window')
    expect(formatEditorCommand(['/opt/meu editor/bin', '--wait'])).toBe('"/opt/meu editor/bin" --wait')
    expect(parseEditorCommand(formatEditorCommand(['a b', "c'd", 'e"f']))).toEqual(['a b', "c'd", 'e"f'])
  })
})
