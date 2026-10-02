import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import RailNode from '../RailNode.vue'
import type { NodeKind } from '../../../conversation/turns'
import type { RailAlign } from '../../../conversation/railAlign'

const KINDS: NodeKind[] = [
  'text', 'thinking', 'read', 'search', 'bash', 'edit', 'task', 'tool', 'agent',
  'running', 'error', 'warning', 'info', 'group',
]

function mountKind(kind: NodeKind) {
  const w = mount(RailNode, { props: { kind } })
  return { root: w.find('[data-test="rail-node"]'), dots: w.findAll('[data-test="rail-dot"]'), w }
}

describe('RailNode', () => {
  it.each(KINDS)('%s: uma bolinha pequena, sem ícone e decorativa', (kind) => {
    const { root, dots, w } = mountKind(kind)
    expect(root.attributes('data-kind')).toBe(kind)
    expect(root.attributes('aria-hidden')).toBe('true')
    expect(dots).toHaveLength(1)
    expect(dots[0]!.classes()).toContain('size-2')
    expect(dots[0]!.classes()).toContain('rounded-full')
    expect(w.find('svg').exists()).toBe(false)
  })

  it('running: âmbar e pulsando, respeitando motion-reduce', () => {
    const cls = mountKind('running').dots[0]!.classes()
    expect(cls).toContain('bg-secondary')
    expect(cls).toContain('animate-pulse')
    expect(cls).toContain('motion-reduce:animate-none')
  })

  it('só o running pulsa', () => {
    for (const kind of KINDS.filter((k) => k !== 'running')) {
      expect(mountKind(kind).dots[0]!.classes()).not.toContain('animate-pulse')
    }
  })

  it('error é vermelha e warning é âmbar', () => {
    expect(mountKind('error').dots[0]!.classes()).toContain('bg-diff-del-fg')
    expect(mountKind('warning').dots[0]!.classes()).toContain('bg-secondary')
  })

  it('text em fg; os demais tipos em cinza', () => {
    expect(mountKind('text').dots[0]!.classes()).toContain('bg-fg')
    for (const kind of ['info', 'thinking', 'read', 'search', 'bash', 'edit', 'task', 'tool', 'agent', 'group'] as NodeKind[]) {
      const cls = mountKind(kind).dots[0]!.classes()
      expect(cls.some((c) => c === 'bg-fg-subtle' || c === 'bg-fg-muted'), kind).toBe(true)
    }
  })

  it('alinhamento vertical pelo tipo de cartão (align), não pelo estado', () => {
    const pt = (kind: NodeKind, align?: RailAlign) => {
      const w = mount(RailNode, { props: { kind, align } })
      return w.find('[data-test="rail-node"]').classes().find((c) => c.startsWith('pt-'))
    }
    expect(pt('text', 'text')).toBe('pt-[18px]')
    expect(pt('running', 'group')).toBe('pt-[18px]')
    expect(pt('group', 'group')).toBe('pt-[18px]')
    expect(pt('thinking', 'thinking')).toBe('pt-1')
    expect(pt('agent', 'agent')).toBe('pt-[17px]')
    expect(pt('read', 'card')).toBe('pt-[13px]')
    // notices: border + py-2 + 20px line
    for (const kind of ['info', 'warning', 'error'] as NodeKind[]) expect(pt(kind, 'notice')).toBe('pt-[15px]')
    // Bash: loose header, text-sm leading-5, in any state
    for (const kind of ['bash', 'running', 'error'] as NodeKind[]) expect(pt(kind, 'bash')).toBe('pt-1.5')
    // the same state over different cards
    expect(pt('error', 'card')).toBe('pt-[13px]')
    expect(pt('running', 'agent')).toBe('pt-[17px]')
    // no align: plain card
    expect(pt('read')).toBe('pt-[13px]')
  })
})
