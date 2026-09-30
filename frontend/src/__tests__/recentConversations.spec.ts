import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { RECENT_MAX, noteOpened, noteRunning, readRecent, recentIds, shownRecentIds } from '../recentConversations'

const KEY = 'vibing:recent-conversations'

beforeEach(() => {
  localStorage.clear()
  recentIds.value = []
  shownRecentIds.value = []
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

describe('ordem estável em Recentes', () => {
  it('abrir uma conversa já visível em Recentes não muda a ordem', () => {
    noteOpened('c'); noteOpened('b'); noteOpened('a') // [a, b, c]
    shownRecentIds.value = ['a', 'b', 'c']
    expect(noteOpened('c')).toEqual(['a', 'b', 'c'])
    expect(readRecent()).toEqual(['a', 'b', 'c'])
  })

  it('abrir uma conversa fora da lista visível leva ao topo', () => {
    noteOpened('c'); noteOpened('b'); noteOpened('a')
    shownRecentIds.value = ['a', 'b']
    expect(noteOpened('c')).toEqual(['c', 'a', 'b'])
  })

  it('noteRunning mantém no lugar quem está visível e leva ao topo quem é novo', () => {
    noteOpened('b'); noteOpened('a') // [a, b]
    shownRecentIds.value = ['a', 'b']
    expect(noteRunning('b')).toEqual(['a', 'b'])
    expect(noteRunning('z')).toEqual(['z', 'a', 'b'])
  })

  it('noteRunning leva ao topo quem está guardado além da lista visível', () => {
    noteOpened('c'); noteOpened('b'); noteOpened('a') // [a, b, c]
    shownRecentIds.value = ['a', 'b']
    expect(noteRunning('c')).toEqual(['c', 'a', 'b'])
    expect(readRecent()).toEqual(['c', 'a', 'b'])
  })
})
