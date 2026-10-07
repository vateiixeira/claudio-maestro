import { describe, expect, it } from 'vitest'
import { deliveriesShortcut } from '../deliveriesShortcut'

function key(init: KeyboardEventInit, target: HTMLElement = document.body) {
  const event = new KeyboardEvent('keydown', init)
  Object.defineProperty(event, 'target', { value: target })
  return event
}

describe('atalhos das entregas', () => {
  it('as setas trocam de dia', () => {
    expect(deliveriesShortcut(key({ key: 'ArrowLeft' }))).toBe('prev')
    expect(deliveriesShortcut(key({ key: 'ArrowRight' }))).toBe('next')
  })

  it('Shift+C copia o dia, o C sozinho não', () => {
    expect(deliveriesShortcut(key({ key: 'C', shiftKey: true }))).toBe('copy')
    expect(deliveriesShortcut(key({ key: 'c' }))).toBeNull()
  })

  it('ignora outras teclas e modificadores', () => {
    expect(deliveriesShortcut(key({ key: 'ArrowUp' }))).toBeNull()
    expect(deliveriesShortcut(key({ key: 'ArrowLeft', ctrlKey: true }))).toBeNull()
    expect(deliveriesShortcut(key({ key: 'ArrowLeft', altKey: true }))).toBeNull()
    expect(deliveriesShortcut(key({ key: 'ArrowRight', shiftKey: true }))).toBeNull()
    expect(deliveriesShortcut(key({ key: 'C', shiftKey: true, ctrlKey: true }))).toBeNull()
  })

  it('ignora campos de texto', () => {
    expect(deliveriesShortcut(key({ key: 'ArrowLeft' }, document.createElement('input')))).toBeNull()
    expect(deliveriesShortcut(key({ key: 'C', shiftKey: true }, document.createElement('textarea')))).toBeNull()
  })
})
