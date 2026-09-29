import { describe, expect, it } from 'vitest'
import { shouldOpenNewConversation } from '../newConversationShortcut'

function key(init: KeyboardEventInit, target: HTMLElement = document.body) {
  const event = new KeyboardEvent('keydown', init)
  Object.defineProperty(event, 'target', { value: target })
  return event
}

describe('atalho C', () => {
  it('abre com C fora de campos de texto', () => {
    expect(shouldOpenNewConversation(key({ key: 'c' }))).toBe(true)
    expect(shouldOpenNewConversation(key({ key: 'C', shiftKey: true }))).toBe(false)
    expect(shouldOpenNewConversation(key({ key: 'c', ctrlKey: true }))).toBe(false)
    expect(shouldOpenNewConversation(key({ key: 'c' }, document.createElement('textarea')))).toBe(false)
    expect(shouldOpenNewConversation(key({ key: 'c' }, document.createElement('input')))).toBe(false)
    const editable = document.createElement('div')
    editable.contentEditable = 'true'
    expect(shouldOpenNewConversation(key({ key: 'c' }, editable))).toBe(false)
  })

  it('não abre com outro diálogo aberto', () => {
    for (const attrs of ['role="dialog"', 'role="alertdialog"', 'aria-modal="true"']) {
      document.body.innerHTML = `<div ${attrs}>ok</div>`
      expect(shouldOpenNewConversation(key({ key: 'c' }))).toBe(false)
    }
    document.body.innerHTML = ''
    expect(shouldOpenNewConversation(key({ key: 'c' }))).toBe(true)
  })

  it('não abre com menu aberto', () => {
    document.body.innerHTML = '<div role="menu"><button role="menuitem">x</button></div>'
    expect(shouldOpenNewConversation(key({ key: 'c' }, document.querySelector('button')!))).toBe(false)
    document.body.innerHTML = ''
  })

  it('diálogo escondido não conta', () => {
    document.body.innerHTML = '<div role="dialog" hidden>x</div><div style="display: none"><div aria-modal="true">y</div></div>'
    expect(shouldOpenNewConversation(key({ key: 'c' }))).toBe(true)
    document.body.innerHTML = ''
  })

  it('não abre se outro tratador já consumiu a tecla ou em campo com role textbox', () => {
    const consumed = new KeyboardEvent('keydown', { key: 'c', cancelable: true })
    consumed.preventDefault()
    expect(shouldOpenNewConversation(consumed)).toBe(false)
    const box = document.createElement('div')
    box.setAttribute('role', 'textbox')
    expect(shouldOpenNewConversation(key({ key: 'c' }, box))).toBe(false)
  })
})
