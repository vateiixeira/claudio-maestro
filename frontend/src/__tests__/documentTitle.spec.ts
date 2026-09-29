import { describe, expect, it } from 'vitest'
import { documentTitle } from '../documentTitle'

describe('título da aba', () => {
  it('mostra o número de conversas aguardando', () => {
    expect(documentTitle(0)).toBe('Vini7 Vibing')
    expect(documentTitle(3)).toBe('(3) Vini7 Vibing')
  })
})
