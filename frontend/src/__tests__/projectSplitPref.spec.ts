import { beforeEach, describe, expect, it, vi } from 'vitest'
import { readSplitPercent, writeSplitPercent } from '../projectSplitPref'

beforeEach(() => {
  localStorage.clear()
  vi.unstubAllGlobals()
})

describe('preferência da divisória da tela do projeto', () => {
  it('começa em 50', () => {
    expect(readSplitPercent()).toBe(50)
  })

  it('lembra o valor gravado', () => {
    writeSplitPercent(40)
    expect(readSplitPercent()).toBe(40)
  })

  it('valor inválido volta para 50', () => {
    for (const bad of ['abc', '', 'NaN', 'Infinity', '{}']) {
      localStorage.setItem('vibing:project-split', bad)
      expect(readSplitPercent()).toBe(50)
    }
  })

  it('valor fora de 30 a 70 é limitado', () => {
    localStorage.setItem('vibing:project-split', '10')
    expect(readSplitPercent()).toBe(30)
    localStorage.setItem('vibing:project-split', '95')
    expect(readSplitPercent()).toBe(70)
  })

  it('funciona sem localStorage', () => {
    vi.stubGlobal('localStorage', {
      getItem() { throw new Error('bloqueado') },
      setItem() { throw new Error('bloqueado') },
    })
    expect(readSplitPercent()).toBe(50)
    expect(() => writeSplitPercent(60)).not.toThrow()
  })
})
