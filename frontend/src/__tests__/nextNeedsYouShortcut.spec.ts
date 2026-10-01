import { describe, expect, it } from 'vitest'
import { shouldGoToNextNeedsYou } from '../nextNeedsYouShortcut'

function key(init: KeyboardEventInit, target: HTMLElement = document.body) {
  const event = new KeyboardEvent('keydown', init)
  Object.defineProperty(event, 'target', { value: target })
  return event
}

describe('atalho N', () => {
  it('vale com N sozinho fora de campos de texto', () => {
    expect(shouldGoToNextNeedsYou(key({ key: 'n' }))).toBe(true)
  })

  it('ignora modificadores', () => {
    expect(shouldGoToNextNeedsYou(key({ key: 'n', ctrlKey: true }))).toBe(false)
    expect(shouldGoToNextNeedsYou(key({ key: 'n', metaKey: true }))).toBe(false)
    expect(shouldGoToNextNeedsYou(key({ key: 'n', altKey: true }))).toBe(false)
    expect(shouldGoToNextNeedsYou(key({ key: 'N', shiftKey: true }))).toBe(false)
  })

  it('ignora outras teclas', () => {
    expect(shouldGoToNextNeedsYou(key({ key: 'c' }))).toBe(false)
  })

  it('ignora campos de texto', () => {
    expect(shouldGoToNextNeedsYou(key({ key: 'n' }, document.createElement('input')))).toBe(false)
    expect(shouldGoToNextNeedsYou(key({ key: 'n' }, document.createElement('textarea')))).toBe(false)
    expect(shouldGoToNextNeedsYou(key({ key: 'n' }, document.createElement('select')))).toBe(false)
    const editable = document.createElement('div')
    editable.contentEditable = 'true'
    expect(shouldGoToNextNeedsYou(key({ key: 'n' }, editable))).toBe(false)
    const attr = document.createElement('div')
    attr.setAttribute('contenteditable', 'true')
    expect(shouldGoToNextNeedsYou(key({ key: 'n' }, attr))).toBe(false)
    const box = document.createElement('div')
    box.setAttribute('role', 'textbox')
    expect(shouldGoToNextNeedsYou(key({ key: 'n' }, box))).toBe(false)
  })

  it('ignora com diálogo ou menu aberto, e tecla já tratada ou em composição', () => {
    document.body.innerHTML = '<div role="dialog">x</div>'
    expect(shouldGoToNextNeedsYou(key({ key: 'n' }))).toBe(false)
    document.body.innerHTML = '<div role="menu">x</div>'
    expect(shouldGoToNextNeedsYou(key({ key: 'n' }))).toBe(false)
    document.body.innerHTML = ''
    expect(shouldGoToNextNeedsYou(key({ key: 'n' }))).toBe(true)
    const consumed = new KeyboardEvent('keydown', { key: 'n', cancelable: true })
    consumed.preventDefault()
    expect(shouldGoToNextNeedsYou(consumed)).toBe(false)
    expect(shouldGoToNextNeedsYou(key({ key: 'n', isComposing: true }))).toBe(false)
  })
})
