import { describe, expect, it } from 'vitest'
import { applySuggestion, findTrigger, mentionText, quotePath, rankCommands } from '../suggestions'
import type { CommandInfo } from '../../types/api'

const cmd = (name: string, description = ''): CommandInfo => ({ name, description, argument_hint: '' })

describe('findTrigger', () => {
  it('acha @ no início, depois de espaço e de quebra de linha', () => {
    expect(findTrigger('@fs', 3)).toEqual({ kind: 'mention', start: 0, end: 3, query: 'fs' })
    expect(findTrigger('veja @fs', 8)).toEqual({ kind: 'mention', start: 5, end: 8, query: 'fs' })
    expect(findTrigger('a\n@fs', 5)).toEqual({ kind: 'mention', start: 2, end: 5, query: 'fs' })
  })
  it('/ só abre o menu no início da mensagem, aceitando espaços e quebras de linha antes', () => {
    expect(findTrigger('/com', 4)).toEqual({ kind: 'command', start: 0, end: 4, query: 'com' })
    expect(findTrigger('  /com', 6)).toEqual({ kind: 'command', start: 2, end: 6, query: 'com' })
    expect(findTrigger('\n \n/com', 7)).toEqual({ kind: 'command', start: 3, end: 7, query: 'com' })
  })
  it('/ fora do início não abre menu', () => {
    expect(findTrigger('salve em /tmp', 13)).toBeNull()
    expect(findTrigger('a\n/com', 6)).toBeNull()
    expect(findTrigger('oi /', 4)).toBeNull()
    expect(findTrigger('/com /tmp', 9)).toBeNull()
  })
  it('@ continua valendo depois de um comando no início', () => {
    expect(findTrigger('/review @fs', 11)).toEqual({ kind: 'mention', start: 8, end: 11, query: 'fs' })
  })
  it('o termo vai até o fim do trecho, mesmo com o cursor no meio', () => {
    expect(findTrigger('@backend/fs x', 3)).toEqual({ kind: 'mention', start: 0, end: 11, query: 'backend/fs' })
  })
  it('ignora e/ou, e-mail e cursor fora do trecho', () => {
    expect(findTrigger('e/ou', 4)).toBeNull()
    expect(findTrigger('a@b.com', 7)).toBeNull()
    expect(findTrigger('@fs depois', 10)).toBeNull()
    expect(findTrigger('@fs', 0)).toBeNull()
  })
  it('/ só vale até a próxima barra, como na extensão', () => {
    expect(findTrigger('/usr/bin', 8)).toBeNull()
    expect(findTrigger('/usr/bin', 4)).toEqual({ kind: 'command', start: 0, end: 4, query: 'usr' })
  })
  it('só / e só @ abrem com termo vazio', () => {
    expect(findTrigger('/', 1)).toEqual({ kind: 'command', start: 0, end: 1, query: '' })
    expect(findTrigger('oi @', 4)).toEqual({ kind: 'mention', start: 3, end: 4, query: '' })
  })
})

describe('applySuggestion', () => {
  it('troca o trecho e põe espaço', () => {
    const t = findTrigger('/com agora', 4)!
    expect(applySuggestion('/com agora', t, '/commit', true)).toEqual({ text: '/commit agora', cursor: 8 })
  })
  it('põe espaço no fim do texto', () => {
    const t = findTrigger('/com', 4)!
    expect(applySuggestion('/com', t, '/commit', true)).toEqual({ text: '/commit ', cursor: 8 })
  })
  it('sem espaço para pasta escolhida com Tab', () => {
    const t = findTrigger('@back', 5)!
    expect(applySuggestion('@back', t, '@backend/', false)).toEqual({ text: '@backend/', cursor: 9 })
  })
})

describe('aspas', () => {
  it('caminho com espaço, aspas ou # vai entre aspas', () => {
    expect(quotePath('a b/c.txt')).toBe('"a b/c.txt"')
    expect(quotePath('a#1.md')).toBe('"a#1.md"')
    expect(quotePath('a"b')).toBe('"a"b"')
    expect(quotePath('src/a.ts')).toBe('src/a.ts')
    expect(mentionText('meu arquivo.md')).toBe('@"meu arquivo.md"')
  })
})

describe('rankCommands', () => {
  const all = [cmd('commit'), cmd('compact-notes'), cmd('code-review', 'Revisa commits'), cmd('superpowers:brainstorming'), cmd('com')]
  it('nome igual, depois prefixo, depois contém/subsequência, depois descrição', () => {
    expect(rankCommands(all, 'com').map((c) => c.name)).toEqual(['com', 'commit', 'compact-notes', 'code-review'])
  })
  it('subsequência casa no grupo 2', () => {
    expect(rankCommands(all, 'sbrain').map((c) => c.name)).toEqual(['superpowers:brainstorming'])
    expect(rankCommands(all, 'superpowers:brain').map((c) => c.name)).toEqual(['superpowers:brainstorming'])
  })
  it('desempata por posição, nome mais curto e ordem alfabética', () => {
    const list = [cmd('xab'), cmd('ab-long'), cmd('ab'), cmd('abc')]
    expect(rankCommands(list, 'ab').map((c) => c.name)).toEqual(['ab', 'abc', 'ab-long', 'xab'])
  })
  it('termo vazio: todos em ordem alfabética', () => {
    expect(rankCommands(all, '').map((c) => c.name)).toEqual(['code-review', 'com', 'commit', 'compact-notes', 'superpowers:brainstorming'])
  })
  it('ignora maiúsculas e minúsculas e descarta o que não casa', () => {
    expect(rankCommands(all, 'COMMIT').map((c) => c.name)).toEqual(['commit', 'code-review'])
    expect(rankCommands(all, 'zzz')).toEqual([])
  })
})
