import { describe, expect, it } from 'vitest'
import { commandFolder, mainInput } from '../tool'

describe('commandFolder', () => {
  it('separa o cd do começo, com && ou ;', () => {
    expect(commandFolder('cd /home/ana/dev/app && git status')).toEqual({ folder: '/home/ana/dev/app', rest: 'git status' })
    expect(commandFolder('cd "pasta com espaço"; ls -la')).toEqual({ folder: 'pasta com espaço', rest: 'ls -la' })
    expect(commandFolder("cd '/tmp/a b' && pwd")).toEqual({ folder: '/tmp/a b', rest: 'pwd' })
  })

  it('sem cd, ou com um cd sozinho, devolve o comando inteiro', () => {
    expect(commandFolder('git status')).toEqual({ folder: null, rest: 'git status' })
    expect(commandFolder('cd /tmp')).toEqual({ folder: null, rest: 'cd /tmp' })
    expect(commandFolder('cd /tmp && ')).toEqual({ folder: null, rest: 'cd /tmp && ' })
    expect(commandFolder('')).toEqual({ folder: null, rest: '' })
  })
})

describe('mainInput', () => {
  it('prefere os campos conhecidos, na ordem', () => {
    expect(mainInput({ query: 'select 1\nfrom t', limit: 3 })).toBe('select 1\nfrom t')
    expect(mainInput({ path: '/a', command: 'ls' })).toBe('ls')
    expect(mainInput({ query: '  ', sql: 'select 2' })).toBe('select 2')
  })

  it('senão, o primeiro valor de texto da entrada', () => {
    expect(mainInput({ n: 1, alvo: 'x', outro: 'y' })).toBe('x')
  })

  it('vazio quando não há texto', () => {
    expect(mainInput({ n: 1 })).toBe('')
    expect(mainInput({})).toBe('')
    expect(mainInput({ a: '   ' })).toBe('')
  })
})
