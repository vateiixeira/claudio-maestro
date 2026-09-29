import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import SubagentStrip from '../SubagentStrip.vue'
import type { SubagentEntry } from '../../../conversation/subagents'

const entry = (id: string, status: SubagentEntry['status'], extra: Partial<SubagentEntry> = {}): SubagentEntry => ({
  id, kind: 'reviewer', description: `desc ${id}`, status, lastAction: `Read ${id}.py`, ...extra,
})
const rows = (w: ReturnType<typeof mount>) => w.findAll('[data-test="subagent-row"]')

describe('faixa de subagentes', () => {
  it('não renderiza nada sem subagentes', () => {
    const w = mount(SubagentStrip, { props: { entries: [] } })
    expect(w.find('[data-test="subagent-strip"]').exists()).toBe(false)
  })

  it('até 3 mostra a lista direto, com tipo, descrição, estado e última ação', () => {
    const w = mount(SubagentStrip, { props: { entries: [entry('a', 'running'), entry('b', 'completed'), entry('c', 'failed')] } })
    expect(w.find('[data-test="subagent-summary"]').exists()).toBe(false)
    expect(rows(w)).toHaveLength(3)
    const first = rows(w)[0]!
    expect(first.text()).toContain('reviewer')
    expect(first.text()).toContain('desc a')
    expect(first.text()).toContain('Read a.py')
    expect(first.find('[data-status="running"]').attributes('aria-label')).toBe('Rodando')
    expect(rows(w)[1]!.find('[data-status="completed"]').attributes('aria-label')).toBe('Concluído')
    expect(rows(w)[2]!.find('[data-status="failed"]').attributes('aria-label')).toBe('Com erro')
  })

  it('estado parado tem rótulo próprio', () => {
    const w = mount(SubagentStrip, { props: { entries: [entry('a', 'running'), entry('b', 'stopped')] } })
    expect(rows(w)[1]!.find('[data-status="stopped"]').attributes('aria-label')).toBe('Parado')
  })

  it('clicar na linha pede para ir ao cartão', async () => {
    const w = mount(SubagentStrip, { props: { entries: [entry('a', 'running'), entry('b', 'completed')] } })
    await rows(w)[1]!.trigger('click')
    expect(w.emitted('select')).toEqual([['b']])
  })

  it('mais de 3 mostra o resumo recolhido; clicar abre a lista e de novo recolhe', async () => {
    const entries = [entry('a', 'running'), entry('b', 'running'), entry('c', 'running'), entry('d', 'completed')]
    const w = mount(SubagentStrip, { props: { entries } })
    const summary = w.find('[data-test="subagent-summary"]')
    expect(summary.text()).toContain('3 rodando, 1 concluído')
    expect(summary.element.tagName).toBe('BUTTON')
    expect(summary.attributes('aria-expanded')).toBe('false')
    expect(rows(w)).toHaveLength(0)
    await summary.trigger('click')
    expect(summary.attributes('aria-expanded')).toBe('true')
    expect(rows(w)).toHaveLength(4)
    await summary.trigger('click')
    expect(rows(w)).toHaveLength(0)
  })

  it('linhas são botões alcançáveis pelo teclado', () => {
    const w = mount(SubagentStrip, { props: { entries: [entry('a', 'running')] } })
    const row = rows(w)[0]!
    expect(row.element.tagName).toBe('BUTTON')
    expect(row.attributes('type')).toBe('button')
  })

  it('região nomeada para leitores de tela', () => {
    const w = mount(SubagentStrip, { props: { entries: [entry('a', 'running')] } })
    const region = w.find('[data-test="subagent-strip"]')
    expect(region.attributes('role')).toBe('region')
    expect(region.attributes('aria-label')).toBe('Subagentes')
  })

  it('sem última ação não deixa linha vazia', () => {
    const w = mount(SubagentStrip, { props: { entries: [entry('a', 'running', { lastAction: '' })] } })
    expect(w.find('[data-test="subagent-last-action"]').exists()).toBe(false)
  })
})
