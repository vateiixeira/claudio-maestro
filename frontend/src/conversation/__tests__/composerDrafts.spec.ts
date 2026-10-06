import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  loadDraftImages,
  loadDraftText,
  resetComposerDrafts,
  saveDraftImages,
  saveDraftText,
} from '../composerDrafts'
import type { DraftImage } from '../images'

const img = (id: number): DraftImage => ({ id, name: `a${id}.png`, size: 3, mediaType: 'image/png', url: 'data:image/png;base64,QUFB' })

beforeEach(() => resetComposerDrafts())
afterEach(() => vi.restoreAllMocks())

describe('rascunho do texto', () => {
  it('guarda por sessão no localStorage', () => {
    saveDraftText('s1', 'olá')
    saveDraftText('s2', 'tchau')
    expect(loadDraftText('s1')).toBe('olá')
    expect(loadDraftText('s2')).toBe('tchau')
    expect(localStorage.getItem('maestro:composer-draft:s1')).toBe('olá')
    expect(loadDraftText('s3')).toBe('')
  })

  it('texto vazio remove a chave', () => {
    saveDraftText('s1', 'olá')
    saveDraftText('s1', '')
    expect(localStorage.getItem('maestro:composer-draft:s1')).toBeNull()
    expect(loadDraftText('s1')).toBe('')
  })

  it('sem storage, vive em memória', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    saveDraftText('s1', 'olá')
    expect(loadDraftText('s1')).toBe('olá')
    saveDraftText('s1', '')
    expect(loadDraftText('s1')).toBe('')
  })
})

describe('rascunho das imagens', () => {
  it('guarda em memória por sessão, sem tocar no localStorage', () => {
    saveDraftImages('s1', [img(1), img(2)])
    expect(loadDraftImages('s1').map((i) => i.id)).toEqual([1, 2])
    expect(loadDraftImages('s2')).toEqual([])
    expect(localStorage.length).toBe(0)
  })

  it('lista vazia apaga', () => {
    saveDraftImages('s1', [img(1)])
    saveDraftImages('s1', [])
    expect(loadDraftImages('s1')).toEqual([])
  })
})
