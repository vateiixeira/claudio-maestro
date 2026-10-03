import { describe, expect, it } from 'vitest'
import { displayStateLabel } from '../sessionState'

describe('displayStateLabel com sessão interrompida', () => {
  it('mostra "Interrompida" quando o turno foi cortado pelo reinício', () => {
    expect(displayStateLabel({ display_state: 'waiting', unread: false, state: 'closed', interrupted: true })).toBe('Interrompida')
  })

  it('não mostra "Interrompida" para uma sessão rodando', () => {
    expect(displayStateLabel({ display_state: 'running', unread: false, state: 'running', interrupted: true })).toBe('Em execução')
  })

  it('mantém o rótulo de sempre sem a marca', () => {
    expect(displayStateLabel({ display_state: 'finished', unread: false, state: 'closed' })).toBe('Finalizada')
  })
})
