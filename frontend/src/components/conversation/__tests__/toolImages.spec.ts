import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { computed } from 'vue'
import { ApiError } from '../../../api/http'
import { SESSION_ID_KEY } from '../../../stores/changesPanel'
import type { ToolItem } from '../../../types/conversation'

vi.mock('../../../api/http', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../../api/http')>()),
  fetchToolImage: vi.fn(),
}))
import { fetchToolImage } from '../../../api/http'
import { resetToolImages, toolImageEntries } from '../../../conversation/toolImages'
import ToolImageStrip from '../ToolImageStrip.vue'
import ImageViewer from '../ImageViewer.vue'
import WorkBlock from '../WorkBlock.vue'
import ReadTool from '../ReadTool.vue'
import GenericTool from '../GenericTool.vue'

const fetchMock = vi.mocked(fetchToolImage)
const marker = (index: number, media_type = 'image/png') => ({ type: 'image', omitted: true, media_type, index, size: 10 })
function tool(id: string, content: unknown, name = 'Read', input: Record<string, unknown> = {}): ToolItem {
  return { type: 'tool', id, tool_use_id: `tu-${id}`, name, input, result: { content, is_error: false, details: null }, streaming: false, parent_tool_use_id: null }
}
const provide = { [SESSION_ID_KEY as symbol]: computed(() => 's1') }
const key = (k: string, init: KeyboardEventInit = {}) => document.dispatchEvent(new KeyboardEvent('keydown', { key: k, ...init }))
const q = (sel: string) => document.body.querySelector<HTMLElement>(`[data-test="${sel}"]`)

let created = 0
const wrappers: VueWrapper[] = []
function track<T extends VueWrapper>(w: T): T { wrappers.push(w); return w }

beforeEach(() => {
  created = 0
  resetToolImages()
  fetchMock.mockReset()
  fetchMock.mockImplementation(async () => new Blob(['x'], { type: 'image/png' }))
  URL.createObjectURL = vi.fn(() => `blob:img-${++created}`)
  URL.revokeObjectURL = vi.fn()
})
afterEach(() => {
  wrappers.splice(0).forEach((w) => w.unmount())
  document.body.innerHTML = ''
})

const three = tool('a', [{ type: 'text', text: 'x' }, marker(0), marker(1), marker(2)], 'Read', { file_path: '/p/tela.png' })

describe('ToolImageStrip', () => {
  it('mostra uma miniatura por imagem, com contador quando são várias', async () => {
    const w = track(mount(ToolImageStrip, { props: { items: [three] }, global: { provide }, attachTo: document.body }))
    await flushPromises()
    const thumbs = w.findAll('[data-test="tool-image"]')
    expect(thumbs).toHaveLength(3)
    expect(thumbs.map((t) => t.attributes('aria-label'))).toEqual(['Abrir imagem 1 de 3', 'Abrir imagem 2 de 3', 'Abrir imagem 3 de 3'])
    expect(w.find('[data-test="tool-image-count"]').text()).toBe('3 imagens')
    expect(w.findAll('img')).toHaveLength(3)
    expect(w.find('img').attributes('src')).toBe('blob:img-1')
    expect(fetchMock).toHaveBeenCalledWith('s1', 'tu-a', 0)
  })

  it('uma imagem só não mostra contador; sem imagens não renderiza nada', async () => {
    const one = track(mount(ToolImageStrip, { props: { items: [tool('b', [marker(0)])] }, global: { provide } }))
    await flushPromises()
    expect(one.find('[data-test="tool-image-count"]').exists()).toBe(false)
    expect(one.findAll('[data-test="tool-image"]')).toHaveLength(1)
    const none = track(mount(ToolImageStrip, { props: { items: [tool('c', 'texto')] }, global: { provide } }))
    expect(none.find('[data-test="tool-image-strip"]').exists()).toBe(false)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('mostra placeholder enquanto carrega e "Imagem indisponível" quando falha', async () => {
    let resolve!: (b: Blob) => void
    fetchMock.mockReturnValueOnce(new Promise<Blob>((r) => { resolve = r }))
    fetchMock.mockRejectedValueOnce(new ApiError(415, null, 'x'))
    const w = track(mount(ToolImageStrip, { props: { items: [tool('d', [marker(0), marker(1)])] }, global: { provide } }))
    await flushPromises()
    const thumbs = w.findAll('[data-test="tool-image"]')
    expect(thumbs[0]!.attributes('aria-busy')).toBe('true')
    expect(thumbs[0]!.find('img').exists()).toBe(false)
    expect(thumbs[1]!.text()).toContain('Imagem indisponível')
    resolve(new Blob(['x']))
    await flushPromises()
    expect(w.findAll('[data-test="tool-image"]')[0]!.find('img').exists()).toBe(true)
  })

  it('rola na horizontal dentro da faixa, sem estourar a largura', () => {
    const w = track(mount(ToolImageStrip, { props: { items: [three] }, global: { provide } }))
    const list = w.find('[data-test="tool-image-list"]')
    expect(list.classes()).toEqual(expect.arrayContaining(['overflow-x-auto']))
    expect(w.classes()).toContain('min-w-0')
  })

  it('clicar numa miniatura abre o visualizador naquela imagem', async () => {
    const w = track(mount(ToolImageStrip, { props: { items: [three] }, global: { provide }, attachTo: document.body }))
    await flushPromises()
    expect(q('image-viewer')).toBeNull()
    await w.findAll('[data-test="tool-image"]')[1]!.trigger('click')
    expect(q('image-viewer')).not.toBeNull()
    expect(q('image-viewer-counter')!.textContent).toBe('2 de 3')
    expect(w.emitted()).not.toHaveProperty('close')
  })

  it('fechar o visualizador devolve o foco à miniatura', async () => {
    const w = track(mount(ToolImageStrip, { props: { items: [three] }, global: { provide }, attachTo: document.body }))
    await flushPromises()
    const thumb = w.findAll('[data-test="tool-image"]')[0]!
    ;(thumb.element as HTMLElement).focus()
    await thumb.trigger('click')
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await flushPromises()
    expect(q('image-viewer')).toBeNull()
    expect(document.activeElement).toBe(thumb.element)
  })
})

describe('ImageViewer', () => {
  const entries = () => toolImageEntries([
    tool('a', [marker(0), marker(1)], 'Read', { file_path: '/p/tela.png' }),
    tool('b', [marker(0)], 'mcp__playwright__browser_take_screenshot'),
  ])
  function open(start = 0) {
    return track(mount(ImageViewer, { props: { entries: entries(), start }, global: { provide }, attachTo: document.body }))
  }
  it('abre no índice pedido, como diálogo modal, com contador e legenda', async () => {
    open(1)
    await flushPromises()
    const dialog = q('image-viewer')!
    expect(dialog.getAttribute('role')).toBe('dialog')
    expect(dialog.getAttribute('aria-modal')).toBe('true')
    expect(q('image-viewer-counter')!.textContent).toBe('2 de 3')
    expect(q('image-viewer-caption')!.textContent).toBe('Read · tela.png')
    expect(fetchMock).toHaveBeenCalledWith('s1', 'tu-a', 1)
    expect(q('image-viewer-image')!.getAttribute('src')).toBe('blob:img-1')
  })

  it('a legenda de uma ferramenta MCP usa servidor · ferramenta', async () => {
    open(2)
    await flushPromises()
    expect(q('image-viewer-caption')!.textContent).toBe('playwright · browser_take_screenshot')
  })

  it('setas do teclado e botões navegam e param nas pontas', async () => {
    const w = open(0)
    await flushPromises()
    const prev = () => q('image-viewer-prev') as HTMLButtonElement
    const next = () => q('image-viewer-next') as HTMLButtonElement
    expect(prev().disabled).toBe(true)
    key('ArrowLeft')
    await flushPromises()
    expect(q('image-viewer-counter')!.textContent).toBe('1 de 3')
    key('ArrowRight')
    await flushPromises()
    expect(q('image-viewer-counter')!.textContent).toBe('2 de 3')
    next().click()
    await flushPromises()
    expect(q('image-viewer-counter')!.textContent).toBe('3 de 3')
    expect(next().disabled).toBe(true)
    key('ArrowRight')
    await flushPromises()
    expect(q('image-viewer-counter')!.textContent).toBe('3 de 3')
    prev().click()
    await flushPromises()
    expect(q('image-viewer-counter')!.textContent).toBe('2 de 3')
    expect(w.emitted('close')).toBeUndefined()
  })

  it('uma imagem só não mostra setas nem contador', async () => {
    track(mount(ImageViewer, { props: { entries: entries().slice(0, 1), start: 0 }, global: { provide }, attachTo: document.body }))
    await flushPromises()
    expect(q('image-viewer-prev')).toBeNull()
    expect(q('image-viewer-counter')).toBeNull()
  })

  it('Esc e o botão fechar emitem close; clicar no fundo também', async () => {
    const w = open(0)
    await flushPromises()
    key('Escape')
    expect(w.emitted('close')).toHaveLength(1)
    ;(q('image-viewer-close') as HTMLButtonElement).click()
    expect(w.emitted('close')).toHaveLength(2)
    q('image-viewer-backdrop')!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    expect(w.emitted('close')).toHaveLength(3)
  })

  it('o foco entra no diálogo e o Tab não sai dele', async () => {
    open(0)
    await flushPromises()
    const panel = q('image-viewer')!
    expect(panel.contains(document.activeElement)).toBe(true)
    const buttons = [...panel.querySelectorAll<HTMLElement>('button:not([disabled])')]
    buttons[buttons.length - 1]!.focus()
    const event = new KeyboardEvent('keydown', { key: 'Tab', cancelable: true })
    document.dispatchEvent(event)
    expect(event.defaultPrevented).toBe(true)
    expect(document.activeElement).toBe(buttons[0])
  })

  it('se as imagens diminuem com o visualizador aberto, limita a posição; vazio, fecha', async () => {
    const all = entries()
    const w = track(mount(ImageViewer, { props: { entries: all, start: 2 }, global: { provide }, attachTo: document.body }))
    await flushPromises()
    expect(q('image-viewer-counter')!.textContent).toBe('3 de 3')
    await w.setProps({ entries: all.slice(0, 2) })
    await flushPromises()
    expect(q('image-viewer-counter')!.textContent).toBe('2 de 2')
    expect(q('image-viewer-caption')!.textContent).toBe('Read · tela.png')
    expect(w.emitted('close')).toBeUndefined()
    await w.setProps({ entries: [] })
    await flushPromises()
    expect(w.emitted('close')).toHaveLength(1)
  })

  it('imagem que falha mostra "Imagem indisponível"', async () => {
    fetchMock.mockRejectedValue(new ApiError(404, null, 'x'))
    open(0)
    await flushPromises()
    expect(q('image-viewer')!.textContent).toContain('Imagem indisponível')
    expect(q('image-viewer-image')).toBeNull()
  })
})

describe('onde a faixa aparece', () => {
  const read = tool('r', [marker(0), marker(1)], 'Read', { file_path: '/p/tela.png' })
  const bash = tool('b', 'ok', 'Bash', { command: 'ls' })
  const shot = tool('s', [{ type: 'text', text: 'feito' }, marker(0)], 'mcp__pw__shot')

  it('WorkBlock fechado mostra a faixa com as imagens de todas as ações, na ordem', async () => {
    const w = track(mount(WorkBlock, { props: { items: [read, bash, shot], open: false, sessionActive: false }, global: { provide }, attachTo: document.body }))
    await flushPromises()
    const strip = w.find('[data-test="tool-image-strip"]')
    expect(strip.exists()).toBe(true)
    expect(w.findAll('[data-test="tool-image"]')).toHaveLength(3)
    expect(w.findAll('[data-test="work-row"]')).toHaveLength(0)
    await w.findAll('[data-test="tool-image"]')[2]!.trigger('click')
    expect(q('image-viewer-counter')!.textContent).toBe('3 de 3')
    expect(q('image-viewer-caption')!.textContent).toBe('pw · shot')
    key('ArrowLeft')
    await flushPromises()
    expect(q('image-viewer-caption')!.textContent).toBe('Read · tela.png')
  })

  it('WorkBlock sem imagens não mostra faixa', async () => {
    const w = track(mount(WorkBlock, { props: { items: [bash], open: true }, global: { provide } }))
    await flushPromises()
    expect(w.find('[data-test="tool-image-strip"]').exists()).toBe(false)
  })

  it('WorkBlock aberto mostra só a faixa do bloco: a linha aberta não repete as imagens, mas mantém o texto', async () => {
    const w = track(mount(WorkBlock, { props: { items: [read, shot], open: true }, global: { provide } }))
    await flushPromises()
    expect(w.findAll('[data-test="tool-image-strip"]')).toHaveLength(1)
    const headers = w.findAll('[data-test="work-row"] [data-test="work-header"]')
    await headers[0]!.trigger('click')
    await headers[1]!.trigger('click')
    expect(w.findAll('[data-test="tool-image-strip"]')).toHaveLength(1)
    expect(w.findAll('[data-test="tool-image"]')).toHaveLength(3)
    expect(w.findAll('[data-test="work-row-body"]')[1]!.text()).toContain('feito')
  })

  it('ReadTool e GenericTool dentro de um WorkBlock (headless) não repetem a faixa; o meta "N imagens" fica', async () => {
    const only = tool('r1', [marker(0), marker(1)], 'Read', { file_path: '/p/a.png' })
    const r = track(mount(ReadTool, { props: { item: only, headless: true }, global: { provide } }))
    await flushPromises()
    expect(r.find('[data-test="tool-image-strip"]').exists()).toBe(false)
    expect(r.find('[data-test="output-box"]').exists()).toBe(false)
    expect(fetchMock).not.toHaveBeenCalled()

    const g = track(mount(GenericTool, { props: { item: shot, headless: true }, global: { provide } }))
    await flushPromises()
    expect(g.find('[data-test="tool-image-strip"]').exists()).toBe(false)
    expect(g.text()).toContain('feito')
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('o meta "N imagens" da linha continua no WorkBlock', async () => {
    const w = track(mount(WorkBlock, { props: { items: [tool('m', [marker(0), marker(1)], 'Read', { file_path: '/p/a.png' })], open: true }, global: { provide } }))
    await flushPromises()
    expect(w.find('[data-test="work-row"] [data-test="work-header"]').text()).toContain('2 imagens')
  })

  it('ReadTool e GenericTool fora de um WorkBlock mostram a faixa da própria ação acima do resultado', async () => {
    const r = track(mount(ReadTool, { props: { item: tool('r2', [{ type: 'text', text: 'linha' }, marker(0)], 'Read', { file_path: '/p/a.png' }) }, global: { provide } }))
    await r.find('[data-test="work-header"]').trigger('click')
    await flushPromises()
    expect(r.findAll('[data-test="tool-image"]')).toHaveLength(1)
    expect(r.text()).not.toContain('Imagem omitida')
    const html = r.html()
    expect(html.indexOf('tool-image-strip')).toBeLessThan(html.indexOf('output-box'))

    const g = track(mount(GenericTool, { props: { item: shot }, global: { provide } }))
    await g.find('[data-test="work-header"]').trigger('click')
    await flushPromises()
    expect(g.findAll('[data-test="tool-image"]')).toHaveLength(1)
    expect(g.text()).toContain('feito')
  })

  it('a ação de um subagente dentro de um WorkBlock mantém a faixa da própria ação', async () => {
    const agent: ToolItem = { type: 'tool', id: 'ag', tool_use_id: 'tu-ag', name: 'Agent', input: { description: 'x' }, result: { content: 'ok', is_error: false, details: null }, streaming: false, parent_tool_use_id: null }
    const child: ToolItem = { ...tool('child', [marker(0)], 'Read', { file_path: '/p/c.png' }), parent_tool_use_id: 'tu-ag' }
    const childrenOf = (id: string) => (id === 'tu-ag' ? [child] : [])
    const w = track(mount(WorkBlock, { props: { items: [agent], open: true, childrenOf }, global: { provide } }))
    await flushPromises()
    await w.find('[data-test="work-row"] [data-test="work-header"]').trigger('click')
    await flushPromises()
    // Not in the block strip (a subagent's action is not the block's own); in the child's own card, once opened.
    expect(w.find('[data-test="tool-image-strip"]').exists()).toBe(false)
    const header = w.findAll('[data-test="work-row-body"] [data-test="work-header"]').find((h) => h.text().includes('c.png'))
    expect(header).toBeTruthy()
    await header!.trigger('click')
    await flushPromises()
    expect(w.findAll('[data-test="tool-image-strip"]')).toHaveLength(1)
  })

  it('ação que só devolveu imagem não mostra uma caixa de texto vazia', async () => {
    const r = track(mount(ReadTool, { props: { item: tool('r3', [marker(0)], 'Read', { file_path: '/p/a.png' }), headless: true }, global: { provide } }))
    await flushPromises()
    expect(r.find('[data-test="output-box"]').exists()).toBe(false)
  })
})
