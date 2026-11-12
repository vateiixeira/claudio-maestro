import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/http'
import type { ToolItem } from '../../types/conversation'

vi.mock('../../api/http', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/http')>()),
  fetchToolImage: vi.fn(),
}))
import { fetchToolImage } from '../../api/http'
import { forgetToolImages, loadToolImage, resetToolImages, toolImageEntries, toolImagesOf } from '../toolImages'
import { resultText } from '../tool'

const fetchMock = vi.mocked(fetchToolImage)
const marker = (index: number, media_type: string | null = 'image/png') => ({ type: 'image', omitted: true, media_type, index, size: 10 })
function tool(id: string, content: unknown, extra: Partial<ToolItem> = {}): ToolItem {
  return { type: 'tool', id, tool_use_id: `tu-${id}`, name: 'Read', input: {}, result: { content, is_error: false, details: null }, streaming: false, parent_tool_use_id: null, ...extra }
}

describe('toolImagesOf', () => {
  it('lista só marcadores renderáveis, com index e tipo permitido', () => {
    const item = tool('a', [
      { type: 'text', text: 'oi' },
      marker(0),
      marker(1, 'image/jpeg'),
      marker(2, 'image/svg+xml'),
      marker(3, null),
      { type: 'image', omitted: true, media_type: 'image/png' },
      { type: 'image', omitted: true, media_type: 'image/webp', index: '4' },
      marker(5, 'image/gif'),
      marker(6, 'image/webp'),
    ])
    expect(toolImagesOf(item).map((i) => [i.index, i.mediaType])).toEqual([
      [0, 'image/png'], [1, 'image/jpeg'], [5, 'image/gif'], [6, 'image/webp'],
    ])
  })

  it('sem resultado ou com conteúdo em texto, não há imagens', () => {
    expect(toolImagesOf(tool('a', 'texto'))).toEqual([])
    expect(toolImagesOf(tool('b', null, { result: null }))).toEqual([])
  })

  it('toolImageEntries junta as imagens de várias ações, na ordem', () => {
    const a = tool('a', [marker(0), marker(1)])
    const b = tool('b', 'sem imagem')
    const c = tool('c', [marker(0)])
    const entries = toolImageEntries([a, b, c])
    expect(entries.map((e) => [e.item.id, e.image.index])).toEqual([['a', 0], ['a', 1], ['c', 0]])
  })
})

describe('resultText com imagens', () => {
  it('marcador renderável não vira texto nem deixa linha vazia', () => {
    expect(resultText([{ type: 'text', text: 'antes' }, marker(0), { type: 'text', text: 'depois' }])).toBe('antes\ndepois')
    expect(resultText([marker(0), marker(1)])).toBe('')
  })

  it('marcador antigo (sem index) ou de tipo não suportado ainda diz "[Imagem omitida]"', () => {
    expect(resultText([{ type: 'image', omitted: true, media_type: 'image/png' }])).toBe('[Imagem omitida]')
    expect(resultText([marker(0, 'image/svg+xml')])).toBe('[Imagem omitida]')
  })
})

describe('loadToolImage', () => {
  let created = 0
  const revoke = vi.fn()
  beforeEach(() => {
    vi.useFakeTimers()
    created = 0
    fetchMock.mockReset()
    revoke.mockReset()
    resetToolImages()
    URL.createObjectURL = vi.fn(() => `blob:img-${++created}`)
    URL.revokeObjectURL = revoke
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('busca uma vez só e compartilha o resultado (inclusive pedidos em voo)', async () => {
    fetchMock.mockResolvedValue(new Blob(['x'], { type: 'image/png' }))
    const [a, b] = await Promise.all([loadToolImage('s1', 'tu-a', 0, () => true), loadToolImage('s1', 'tu-a', 0, () => true)])
    const c = await loadToolImage('s1', 'tu-a', 0, () => true)
    expect(a).toBe('blob:img-1')
    expect(b).toBe(a)
    expect(c).toBe(a)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock).toHaveBeenCalledWith('s1', 'tu-a', 0)
    await loadToolImage('s1', 'tu-a', 1, () => true)
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('em 404, tenta de novo após 1 s, 2 s e 4 s enquanto a sessão está ativa', async () => {
    fetchMock
      .mockRejectedValueOnce(new ApiError(404, null, 'x'))
      .mockRejectedValueOnce(new ApiError(404, null, 'x'))
      .mockRejectedValueOnce(new ApiError(404, null, 'x'))
      .mockResolvedValueOnce(new Blob(['x']))
    const promise = loadToolImage('s1', 'tu-a', 0, () => true)
    await vi.advanceTimersByTimeAsync(0)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(999)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1)
    expect(fetchMock).toHaveBeenCalledTimes(2)
    await vi.advanceTimersByTimeAsync(2000)
    expect(fetchMock).toHaveBeenCalledTimes(3)
    await vi.advanceTimersByTimeAsync(4000)
    expect(fetchMock).toHaveBeenCalledTimes(4)
    await expect(promise).resolves.toBe('blob:img-1')
  })

  it('desiste depois de 3 novas tentativas e não guarda a falha', async () => {
    fetchMock.mockRejectedValue(new ApiError(404, null, 'x'))
    const promise = loadToolImage('s1', 'tu-a', 0, () => true)
    const settled = promise.catch((e) => e)
    await vi.advanceTimersByTimeAsync(7000)
    expect(await settled).toMatchObject({ status: 404 })
    expect(fetchMock).toHaveBeenCalledTimes(4)
    fetchMock.mockResolvedValue(new Blob(['x']))
    await expect(loadToolImage('s1', 'tu-a', 0, () => true)).resolves.toBe('blob:img-1')
  })

  it('sem sessão ativa, 404 falha de uma vez; outros erros não repetem', async () => {
    fetchMock.mockRejectedValue(new ApiError(404, null, 'x'))
    await expect(loadToolImage('s1', 'tu-a', 0, () => false)).rejects.toMatchObject({ status: 404 })
    expect(fetchMock).toHaveBeenCalledTimes(1)
    fetchMock.mockReset()
    fetchMock.mockRejectedValue(new ApiError(415, null, 'x'))
    await expect(loadToolImage('s1', 'tu-b', 0, () => true)).rejects.toMatchObject({ status: 415 })
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('a sessão deixa de estar ativa no meio das tentativas: para de tentar', async () => {
    fetchMock.mockRejectedValue(new ApiError(404, null, 'x'))
    let active = true
    const settled = loadToolImage('s1', 'tu-a', 0, () => active).catch((e) => e)
    await vi.advanceTimersByTimeAsync(0)
    active = false
    await vi.advanceTimersByTimeAsync(1000)
    expect(await settled).toMatchObject({ status: 404 })
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('forgetToolImages revoga só as URLs daquela sessão', async () => {
    fetchMock.mockResolvedValue(new Blob(['x']))
    await loadToolImage('s1', 'tu-a', 0, () => true)
    await loadToolImage('s1', 'tu-a', 1, () => true)
    await loadToolImage('s2', 'tu-a', 0, () => true)
    forgetToolImages('s1')
    expect(revoke.mock.calls.map((c) => c[0]).sort()).toEqual(['blob:img-1', 'blob:img-2'])
    await loadToolImage('s1', 'tu-a', 0, () => true)
    expect(fetchMock).toHaveBeenCalledTimes(4)
    await loadToolImage('s2', 'tu-a', 0, () => true)
    expect(fetchMock).toHaveBeenCalledTimes(4)
  })

  it('imagem que chega depois do forget é revogada em vez de guardada', async () => {
    let resolve!: (b: Blob) => void
    fetchMock.mockReturnValue(new Promise<Blob>((r) => { resolve = r }))
    const promise = loadToolImage('s1', 'tu-a', 0, () => true).catch((e) => e)
    forgetToolImages('s1')
    resolve(new Blob(['x']))
    await promise
    expect(revoke).toHaveBeenCalledWith('blob:img-1')
  })
})
