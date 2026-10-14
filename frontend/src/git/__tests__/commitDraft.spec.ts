import { afterEach, describe, expect, it, vi } from 'vitest'
import { clearDraft, readDraft, writeDraft } from '../commitDraft'

afterEach(() => { localStorage.clear(); vi.restoreAllMocks() })

describe('rascunho da mensagem de commit', () => {
  it('guarda por repositório e limpa', () => {
    writeDraft('/a', 'Mensagem A')
    writeDraft('/b', 'Mensagem B')
    expect(readDraft('/a')).toBe('Mensagem A')
    clearDraft('/a')
    expect(readDraft('/a')).toBe('')
    expect(readDraft('/b')).toBe('Mensagem B')
  })
  it('texto vazio apaga e localStorage indisponível não quebra', () => {
    writeDraft('/a', 'x')
    writeDraft('/a', '')
    expect(localStorage.length).toBe(0)
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('bloqueado') })
    expect(readDraft('/a')).toBe('')
  })
})
