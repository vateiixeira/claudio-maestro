import { describe, expect, it } from 'vitest'
import { attachImages } from '../images'

function png(name = 'a.png', bytes = 3, type = 'image/png') {
  return new File([new Uint8Array(bytes).fill(65)], name, { type })
}
function sized(name: string, bytes: number) {
  const file = png(name)
  Object.defineProperty(file, 'size', { value: bytes })
  return file
}

describe('attachImages', () => {
  it('lê as imagens aceitas e não dá erro', async () => {
    const result = await attachImages([], [png('a.png'), png('b.webp', 3, 'image/webp')])
    expect(result.error).toBeNull()
    expect(result.added.map((i) => i.name)).toEqual(['a.png', 'b.webp'])
    expect(result.added[0]!.url).toMatch(/^data:image\/png;base64,/)
  })

  it('recusa formato e tamanho, mas aceita o resto', async () => {
    const result = await attachImages([], [png('doc.pdf', 3, 'application/pdf'), sized('grande.png', 5 * 1024 * 1024 + 1), png('ok.png')])
    expect(result.added.map((i) => i.name)).toEqual(['ok.png'])
    expect(result.error).toContain('doc.pdf')
    expect(result.error).toContain('5 MB')
  })

  it('respeita o limite de 10 imagens contando as já anexadas', async () => {
    const current = (await attachImages([], Array.from({ length: 8 }, (_, i) => png(`c${i}.png`)))).added
    const result = await attachImages(current, Array.from({ length: 4 }, (_, i) => png(`n${i}.png`)))
    expect(result.added).toHaveLength(2)
    expect(result.error).toContain('10 imagens')
  })

  it('respeita o limite de 30 MB somando as imagens', async () => {
    const result = await attachImages([], Array.from({ length: 7 }, (_, i) => sized(`g${i}.png`, 5 * 1024 * 1024)))
    expect(result.added).toHaveLength(6)
    expect(result.error).toContain('30 MB')
  })
})
