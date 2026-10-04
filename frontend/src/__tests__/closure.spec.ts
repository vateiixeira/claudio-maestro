import { describe, expect, it } from 'vitest'
import { shownVerdict } from '../closure'

const s = (closure_verdict: string | null, display_state: string) => ({ closure_verdict, display_state }) as never

describe('shownVerdict', () => {
  it('mostra o veredito de uma conversa que espera', () => {
    expect(shownVerdict(s('can_close', 'waiting'))).toBe('can_close')
    expect(shownVerdict(s('incomplete', 'waiting'))).toBe('incomplete')
  })

  it.each([['finished'], ['running']])('não mostra nada em %s', (state) => {
    expect(shownVerdict(s('can_close', state))).toBeNull()
  })

  it('não mostra em andamento nem sem veredito', () => {
    expect(shownVerdict(s('in_progress', 'waiting'))).toBeNull()
    expect(shownVerdict(s(null, 'waiting'))).toBeNull()
  })
})
