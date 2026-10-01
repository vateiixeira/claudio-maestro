import { describe, expect, it } from 'vitest'
import { documentTitle } from '../documentTitle'

describe('título da aba', () => {
  it('mostra o número de conversas aguardando', () => {
    expect(documentTitle(0)).toBe('Cláudio Maestro')
    expect(documentTitle(3)).toBe('(3) Cláudio Maestro')
  })
})
