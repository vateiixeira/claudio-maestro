import { afterEach, describe, expect, it, vi } from 'vitest'
import { clearDraft, readDraft, readMergeMessage, writeDraft, writeMergeMessage } from '../commitDraft'

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
  it('a mensagem de merge preenchida pelo app fica guardada à parte, por repositório', () => {
    writeMergeMessage('/a', "Merge branch 'x'")
    expect(readMergeMessage('/a')).toBe("Merge branch 'x'")
    expect(readMergeMessage('/b')).toBeNull()
    expect(readDraft('/a')).toBe('')
    writeMergeMessage('/a', null)
    expect(readMergeMessage('/a')).toBeNull()
    expect(localStorage.length).toBe(0)
  })
})
