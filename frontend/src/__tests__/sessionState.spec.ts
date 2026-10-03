import { describe, expect, it } from 'vitest'
import { deriveDisplay, displayStateLabel } from '../sessionState'

describe('deriveDisplay', () => {
  it('fechada com o CLI no meio de um turno fica em execução', () => {
    expect(deriveDisplay('closed', false, 'waiting', true).display_state).toBe('running')
    expect(deriveDisplay('closed', false, 'waiting').display_state).toBe('waiting')
    expect(deriveDisplay('idle', false, 'waiting', true).display_state).toBe('waiting')
  })

  it('sessão ociosa com subagente rodando fica em execução', () => {
    expect(deriveDisplay('idle', false, 'waiting', false, true).display_state).toBe('running')
    expect(deriveDisplay('idle', false, 'waiting', false, false).display_state).toBe('waiting')
    // Without a client there is no subagent of the app: the flag is ignored.
    expect(deriveDisplay('closed', false, 'waiting', false, true).display_state).toBe('waiting')
    expect(deriveDisplay('closed', true, 'finished', false, true).display_state).toBe('finished')
  })

  it('o rótulo falado de uma marcada não lida, sem pedido real, é "Sua vez"', () => {
    expect(displayStateLabel({ display_state: 'waiting', unread: true, state: 'idle', mark: 'blocked' })).toBe('Sua vez')
    expect(displayStateLabel({ display_state: 'waiting', unread: true, state: 'idle' })).toBe('Aguardando você')
    expect(displayStateLabel({ display_state: 'waiting', unread: false, state: 'idle', mark: 'blocked', pending_kind: 'tool' })).toBe('Aguardando você')
  })
})
