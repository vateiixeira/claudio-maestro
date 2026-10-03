import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import RailNode from '../RailNode.vue'
import WorkHeader from '../WorkHeader.vue'
import ThinkingBlock from '../ThinkingBlock.vue'
import type { NodeKind } from '../../../conversation/turns'
import type { RailAlign } from '../../../conversation/railAlign'

type WorkKindName = 'bash' | 'tool' | 'read' | 'search' | 'edit' | 'agent'
const WORK: Array<[WorkKindName, 'command' | 'file' | 'agent']> = [
  ['bash', 'command'], ['tool', 'command'], ['read', 'file'], ['search', 'file'], ['edit', 'file'], ['agent', 'agent'],
]
const DOTS: NodeKind[] = ['text', 'task', 'info', 'warning']

function mountKind(kind: NodeKind, align?: RailAlign) {
  const w = mount(RailNode, { props: { kind, align } })
  return { w, root: w.find('[data-test="rail-node"]'), dot: w.find('[data-test="rail-dot"]'), ring: w.find('[data-test="rail-ring"]'), svg: w.find('svg') }
}
// The drawing of an icon, without the svg's own attributes (size, classes).
const inner = (html: string) => html.replace(/^<svg[^>]*>/, '').replace(/<\/svg>$/, '')
const mix = (token: string) => `border-[color-mix(in_oklab,var(--color-${token})_55%,transparent)]`

describe('RailNode: todo nó é decorativo e leva o tipo', () => {
  it.each([...DOTS, 'thinking', 'running', 'waiting', 'error', ...WORK.map(([k]) => k)] as NodeKind[])('%s', (kind) => {
    const { root } = mountKind(kind)
    expect(root.attributes('data-kind')).toBe(kind)
    expect(root.attributes('aria-hidden')).toBe('true')
  })
})

describe('RailNode: texto e avisos são um ponto de 7px', () => {
  it.each(DOTS)('%s: ponto redondo de 7px com anel da cor do fundo e sem ícone', (kind) => {
    const { dot, ring, svg } = mountKind(kind)
    expect(dot.exists()).toBe(true)
    expect(dot.classes()).toEqual(expect.arrayContaining(['size-[7px]', 'rounded-full', 'shadow-[0_0_0_4px_var(--color-surface)]']))
    expect(ring.exists()).toBe(false)
    expect(svg.exists()).toBe(false)
  })

  it('texto e tarefa em fg-muted, aviso em secondary, informação em fg-subtle', () => {
    expect(mountKind('text').dot.classes()).toContain('bg-fg-muted')
    expect(mountKind('task').dot.classes()).toContain('bg-fg-muted')
    expect(mountKind('warning').dot.classes()).toContain('bg-secondary')
    expect(mountKind('info').dot.classes()).toContain('bg-fg-subtle')
  })

  it('nenhum ponto pulsa', () => {
    for (const kind of DOTS) expect(mountKind(kind).dot.classes()).not.toContain('animate-pulse')
  })
})

describe('RailNode: raciocínio', () => {
  it('anel de 18px com a lâmpada no tom de raciocínio', () => {
    const { ring, svg, dot } = mountKind('thinking')
    expect(dot.exists()).toBe(false)
    expect(ring.classes()).toEqual(expect.arrayContaining(['size-[18px]', 'rounded-full', 'border', 'bg-surface', 'text-type-think', mix('type-think')]))
    expect(svg.exists()).toBe(true)
  })

  it('a lâmpada é a mesma do bloco de raciocínio', () => {
    const think = mount(ThinkingBlock, { props: { item: { type: 'thinking', id: 't', text: 'x', streaming: false, parent_tool_use_id: null } } })
    expect(inner(mountKind('thinking').svg.html())).toBe(inner(think.find('[data-test="thinking-icon"]').html()))
  })
})

describe('RailNode: bloco de trabalho', () => {
  it.each(WORK)('%s: anel de 22px com o ícone e o tom da família %s', (kind, family) => {
    const { ring, svg, dot } = mountKind(kind)
    expect(dot.exists()).toBe(false)
    expect(ring.classes()).toEqual(expect.arrayContaining(['size-[22px]', 'rounded-full', 'border', 'bg-surface', `text-type-${family}`, mix(`type-${family}`)]))
    expect(svg.exists()).toBe(true)
  })

  it.each(WORK)('%s: o ícone é o mesmo do cabeçalho da ação', (kind) => {
    const header = mount(WorkHeader, { props: { kind, desc: 'x', status: 'ok' } })
    expect(inner(mountKind(kind).svg.html())).toBe(inner(header.find('[data-test="work-icon"]').html()))
  })
})

describe('RailNode: estados vencem o tipo', () => {
  it('rodando: spinner secondary com borda laranja, que respeita motion-reduce', () => {
    const { ring, svg } = mountKind('running')
    expect(ring.classes()).toEqual(expect.arrayContaining(['size-[22px]', 'rounded-full', 'border-secondary', 'bg-surface']))
    expect(svg.classes()).toEqual(expect.arrayContaining(['text-secondary', 'animate-spin', 'motion-reduce:animate-none']))
    expect(ring.classes().join(' ')).not.toContain('type-')
  })

  it('esperando você: triângulo com "!" em secondary, como o ícone de estado do app', () => {
    const { ring, svg } = mountKind('waiting')
    expect(ring.classes()).toEqual(expect.arrayContaining(['size-[22px]', 'text-secondary', mix('secondary')]))
    expect(svg.classes()).not.toContain('animate-spin')
    expect(svg.attributes('data-shape')).toBe('triangle')
    expect(svg.html()).toContain('M12 3 2 20h20L12 3z')
    expect(svg.html()).toContain('M12 10v4')
  })

  it('erro: círculo com "×" em diff-del-fg, do tamanho do anel', () => {
    const { ring, svg } = mountKind('error')
    expect(ring.classes()).toEqual(expect.arrayContaining(['size-[22px]', 'rounded-full', 'bg-surface', 'text-diff-del-fg']))
    expect(svg.attributes('data-shape')).toBe('circle-x')
    expect(svg.attributes('width')).toBe('22')
    expect(svg.find('circle').exists()).toBe(true)
    expect(svg.html()).toContain('m9 9 6 6')
    expect(svg.html()).not.toContain('M12 3 2 20h20L12 3z')
  })

  it('erro e esperando você têm formas diferentes, nunca só a cor', () => {
    const waiting = mountKind('waiting').svg
    const error = mountKind('error').svg
    expect(waiting.attributes('data-shape')).not.toBe(error.attributes('data-shape'))
    expect(inner(waiting.html())).not.toBe(inner(error.html()))
  })

  it('só o spinner gira', () => {
    for (const kind of ['text', 'thinking', 'waiting', 'error', 'read', 'bash'] as NodeKind[]) {
      expect(mountKind(kind).w.html()).not.toContain('animate-')
    }
  })
})

describe('RailNode: alinhamento vertical', () => {
  // The node's center sits on the middle of the first line of the card next to it:
  // padding-top = center of the line - half the node.
  const top = (kind: NodeKind, align?: RailAlign) => {
    const style = mountKind(kind, align).root.attributes('style') ?? ''
    return Number(/padding-top:\s*([\d.]+)px/.exec(style)?.[1])
  }

  it('o centro cai no meio da primeira linha de cada cartão, seja qual for o nó', () => {
    // text: 12; thinking block (py-1.5 + 16px line): 14; notice: 19; work block header (44px): 22; plain card: 17
    expect(top('text', 'text') + 3.5).toBe(12)
    expect(top('thinking', 'thinking') + 9).toBe(14)
    expect(top('info', 'notice') + 3.5).toBe(19)
    expect(top('error', 'notice') + 11).toBe(19)
    expect(top('read', 'group') + 11).toBe(22)
    expect(top('running', 'group') + 11).toBe(22)
    expect(top('waiting', 'group') + 11).toBe(22)
    expect(top('task', 'card') + 3.5).toBe(17)
  })

  it('sem align, o cartão comum', () => {
    expect(top('task') + 3.5).toBe(17)
  })
})
