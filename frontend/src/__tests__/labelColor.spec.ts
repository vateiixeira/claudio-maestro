import { describe, expect, it } from 'vitest'
import { LABEL_PALETTE, LABEL_TINT, labelStyle, mixHex } from '../labelColor'

describe('cor das etiquetas', () => {
  it('o fundo é a cor da etiqueta a 24% sobre a superfície, com texto em fg e ponto na cor cheia', () => {
    expect(LABEL_TINT).toBe(24)
    expect(labelStyle('#6366f1')).toEqual({
      backgroundColor: 'color-mix(in srgb, #6366f1 24%, var(--color-elevated))',
      color: 'var(--color-fg)',
      '--label-dot': '#6366f1',
    })
  })

  it('aceita a forma curta e maiúsculas', () => {
    expect(labelStyle('#FFF')['--label-dot']).toBe('#ffffff')
    expect(labelStyle('#1D4ED8')['--label-dot']).toBe('#1d4ed8')
  })

  it('uma cor inválida cai num cinza, sem quebrar', () => {
    expect(labelStyle('nada')['--label-dot']).toBe('#6b7280')
    expect(labelStyle('')['--label-dot']).toBe('#6b7280')
  })

  it('mixHex mistura a cor com a base na porcentagem dada', () => {
    expect(mixHex('#ffffff', '#000000', 24)).toBe('#3d3d3d')
    expect(mixHex('#ff0000', '#0000ff', 100)).toBe('#ff0000')
    expect(mixHex('#ff0000', '#0000ff', 0)).toBe('#0000ff')
  })

  it('a paleta tem as sete cores fixas, nessa ordem', () => {
    expect(LABEL_PALETTE).toEqual(['#ff6188', '#fc9867', '#ffd866', '#a9dc76', '#78dce8', '#ab9df2', '#9e9d9d'])
  })
})
