import { describe, expect, it } from 'vitest'
import { shortModelLabel } from '../modelLabel'

describe('shortModelLabel', () => {
  it('tira o parêntese final', () => {
    expect(shortModelLabel('Default (recommended)')).toBe('Default')
    expect(shortModelLabel('Sonnet 5 (1M context)')).toBe('Sonnet 5')
  })

  it('mantém o nome sem parêntese', () => {
    expect(shortModelLabel('Opus 5.5')).toBe('Opus 5.5')
  })

  it('não deixa o nome vazio', () => {
    expect(shortModelLabel('(x)')).toBe('(x)')
    expect(shortModelLabel('  (x)  ')).toBe('(x)')
  })
})
