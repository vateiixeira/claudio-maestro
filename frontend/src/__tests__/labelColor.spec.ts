import { describe, expect, it } from 'vitest'
import { contrastText, labelStyle } from '../labelColor'

describe('cor das etiquetas', () => {
  it('escolhe o texto de maior contraste', () => {
    expect(contrastText('#ffffff')).toBe('#000000')
    expect(contrastText('#facc15')).toBe('#000000')
    expect(contrastText('#ff0000')).toBe('#000000')
    expect(contrastText('#000000')).toBe('#ffffff')
    expect(contrastText('#1d4ed8')).toBe('#ffffff')
  })

  it('aceita a forma curta e maiúsculas', () => {
    expect(contrastText('#FFF')).toBe('#000000')
    expect(contrastText('#000')).toBe('#ffffff')
  })

  it('uma cor inválida cai num cinza legível, sem quebrar', () => {
    expect(labelStyle('xyz')).toEqual({ backgroundColor: '#6b7280', color: '#ffffff' })
  })

  it('devolve o fundo na cor da etiqueta', () => {
    expect(labelStyle('#1D4ED8')).toEqual({ backgroundColor: '#1d4ed8', color: '#ffffff' })
  })
})
