import { describe, expect, it } from 'vitest'
import { deriveDisplay } from '../sessionState'

describe('deriveDisplay', () => {
  it('fechada com o CLI no meio de um turno fica em execução', () => {
    expect(deriveDisplay('closed', false, 'waiting', true).display_state).toBe('running')
    expect(deriveDisplay('closed', false, 'waiting').display_state).toBe('waiting')
    expect(deriveDisplay('idle', false, 'waiting', true).display_state).toBe('waiting')
  })
})
