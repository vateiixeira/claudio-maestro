import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { RECENT_MAX, noteOpened, readRecent, recentIds } from '../recentConversations'

const KEY = 'vibing:recent-conversations'

beforeEach(() => {
  localStorage.clear()
  recentIds.value = []
})
afterEach(() => vi.unstubAllGlobals())

describe('conversas abertas recentemente', () => {
  it('começa vazio', () => {
    expect(readRecent()).toEqual([])
  })

  it('guarda a mais recente primeiro', () => {
    noteOpened('a')
    noteOpened('b')
    noteOpened('c')
    expect(readRecent()).toEqual(['c', 'b', 'a'])
    expect(JSON.parse(localStorage.getItem(KEY)!)).toEqual(['c', 'b', 'a'])
    expect(recentIds.value).toEqual(['c', 'b', 'a'])
  })

  it('reabrir move para o topo, sem duplicar', () => {
    noteOpened('a')
    noteOpened('b')
    noteOpened('c')
    expect(noteOpened('a')).toEqual(['a', 'c', 'b'])
    expect(readRecent()).toEqual(['a', 'c', 'b'])
  })

  it('guarda no máximo 20', () => {
    expect(RECENT_MAX).toBe(20)
    for (let i = 0; i < 25; i++) noteOpened(`s${i}`)
    const ids = readRecent()
    expect(ids).toHaveLength(20)
    expect(ids[0]).toBe('s24')
    expect(ids[19]).toBe('s5')
  })

  it('com localStorage que lança erro, lê [] e não quebra ao gravar', () => {
    vi.stubGlobal('localStorage', {
      getItem() { throw new Error('bloqueado') },
      setItem() { throw new Error('bloqueado') },
    })
    expect(readRecent()).toEqual([])
    expect(() => noteOpened('a')).not.toThrow()
    expect(recentIds.value).toEqual(['a'])
  })

  it.each(['não é json', '{"a":1}', '"texto"', '[1,2]', '["a",null]'])('valor inválido (%s) vira []', (raw) => {
    localStorage.setItem(KEY, raw)
    expect(readRecent()).toEqual([])
  })
})
