import { describe, expect, it } from 'vitest'
import { noticeDayLabel, noticeFullBody, noticeParts } from '../noticeText'

// "Now" is Tuesday 2026-11-17, 10:40, local time.
const now = new Date(2026, 10, 17, 10, 40)
const at = (y: number, m: number, d: number, h: number) => new Date(y, m - 1, d, h).getTime() / 1000

describe('noticeParts', () => {
  it('a primeira linha é o título e o resto vira o corpo, sem os asteriscos', () => {
    expect(noticeParts('Rotina de 12/11.\n\n**Vistas:** 42 itens, 6 novos.')).toEqual({
      headline: 'Rotina de 12/11.',
      body: 'Vistas: 42 itens, 6 novos.',
    })
  })

  it('uma linha só não tem corpo', () => {
    expect(noticeParts('Uma linha só')).toEqual({ headline: 'Uma linha só', body: '' })
  })

  it('pula as linhas vazias do começo e junta as demais por espaço', () => {
    expect(noticeParts('  \nTítulo\nlinha 2\nlinha 3')).toEqual({ headline: 'Título', body: 'linha 2 linha 3' })
  })

  it('texto vazio não tem título nem corpo', () => {
    expect(noticeParts('  \n ')).toEqual({ headline: '', body: '' })
  })
})

describe('noticeFullBody', () => {
  it('mantém os parágrafos e tira os asteriscos', () => {
    expect(noticeFullBody('Título\n\n**Vistas:** 42.\nSegunda linha.\n\n\n\nOutro parágrafo.')).toBe(
      'Vistas: 42.\nSegunda linha.\n\nOutro parágrafo.',
    )
  })

  it('uma linha só não tem corpo', () => {
    expect(noticeFullBody('Só o título')).toBe('')
  })
})

describe('noticeDayLabel', () => {
  it('hoje e ontem', () => {
    expect(noticeDayLabel(at(2026, 11, 17, 8), now)).toBe('Hoje')
    expect(noticeDayLabel(at(2026, 11, 16, 23), now)).toBe('Ontem')
  })

  it('outro dia do ano mostra o dia, o mês e o dia da semana', () => {
    expect(noticeDayLabel(at(2026, 11, 13, 18), now)).toBe('13 nov · sexta')
    expect(noticeDayLabel(at(2026, 11, 9, 8), now)).toBe('9 nov · segunda')
    expect(noticeDayLabel(at(2026, 5, 2, 8), now)).toBe('2 mai · sábado')
  })

  it('outro ano mostra o ano', () => {
    expect(noticeDayLabel(at(2025, 12, 30, 8), now)).toBe('30 dez 2025 · terça')
  })
})
