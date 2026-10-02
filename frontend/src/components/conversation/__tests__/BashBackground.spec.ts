import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { ref } from 'vue'
import { SUBAGENT_FOCUS_KEY, type SubagentFocus } from '../../../conversation/subagents'
import BashTool from '../BashTool.vue'
import type { ToolItem } from '../../../types/conversation'

const LAUNCHED = { content: 'Command running in background with ID: b1.', is_error: false, details: null }

function bash(overrides: Partial<ToolItem> = {}): ToolItem {
  return {
    type: 'tool', id: 't', tool_use_id: 'tu', name: 'Bash',
    input: { command: 'sleep 8; echo done', run_in_background: true },
    result: LAUNCHED, streaming: false, parent_tool_use_id: null, ...overrides,
  }
}
const live = (status: 'running' | 'completed' | 'failed' | 'stopped', summary: string | null = null) => ({ task_id: 'b1', status, summary })
const badge = (item: ToolItem) => mount(BashTool, { props: { item, sessionActive: true } }).find('[data-test="bash-background"]')

describe('Bash em background', () => {
  it('comando comum não mostra selo', () => {
    const w = mount(BashTool, { props: { item: bash({ input: { command: 'ls' }, background: null }), sessionActive: true } })
    expect(w.find('[data-test="bash-background"]').exists()).toBe(false)
  })

  it('rodando: selo "Em background" com indicador pulsante', () => {
    const el = badge(bash({ background: live('running') }))
    expect(el.attributes('data-status')).toBe('running')
    expect(el.text()).toContain('Em background')
    expect(el.classes()).toContain('text-secondary-soft')
    expect(el.classes()).not.toContain('text-primary-soft')
    expect(el.find('[data-test="bash-background-dot"]').classes()).toContain('bg-secondary')
    expect(el.find('[data-test="bash-background-dot"]').classes()).not.toContain('bg-primary')
    expect(el.find('[data-test="bash-background-dot"]').classes()).toContain('animate-pulse')
    expect(el.find('[data-test="bash-background-dot"]').classes()).toContain('motion-reduce:animate-none')
  })

  it('concluído, falhou e parado', () => {
    expect(badge(bash({ background: live('completed') })).text()).toContain('Concluído')
    expect(badge(bash({ background: live('completed') })).classes()).toContain('text-primary-soft')
    expect(badge(bash({ background: live('failed') })).text()).toContain('Falhou')
    expect(badge(bash({ background: live('stopped') })).text()).toContain('Parado')
    expect(badge(bash({ background: live('completed') })).find('[data-test="bash-background-dot"]').exists()).toBe(false)
  })

  it('sem status ao vivo (histórico) o rótulo é neutro e sem pulso', () => {
    const el = badge(bash())
    expect(el.attributes('data-status')).toBe('unknown')
    expect(el.text()).toContain('Em background')
    expect(el.find('[data-test="bash-background-dot"]').exists()).toBe(false)
  })

  it('mostra o resumo, discreto, quando existe', () => {
    const w = mount(BashTool, { props: { item: bash({ background: live('completed', 'Background command completed (exit code 0)') }), sessionActive: true } })
    expect(w.find('[data-test="bash-background-summary"]').text()).toContain('exit code 0')
    const none = mount(BashTool, { props: { item: bash({ background: live('running') }), sessionActive: true } })
    expect(none.find('[data-test="bash-background-summary"]').exists()).toBe(false)
  })

  it('antes do resultado a bolinha pulsa e o "rodando…" fica só para leitor de tela', () => {
    const w = mount(BashTool, { props: { item: bash({ result: null, background: null }), sessionActive: true } })
    expect(w.find('[data-test="bash-header"] .sr-only').text()).toBe('rodando…')
    expect(w.find('[data-test="bash-status-dot"]').classes()).toContain('animate-pulse')
  })

  it('falha em background deixa a bolinha vermelha', () => {
    const w = mount(BashTool, { props: { item: bash({ background: live('failed') }), sessionActive: true } })
    expect(w.find('[data-test="bash-status-dot"]').attributes('data-state')).toBe('error')
  })

  it('o selo é o único estado no cabeçalho depois do resultado', () => {
    const w = mount(BashTool, { props: { item: bash({ background: live('running') }), sessionActive: true } })
    const header = w.find('[data-test="bash-header"]').text()
    expect(header).toContain('Em background')
    expect(header).not.toContain('rodando')
    expect(header).not.toContain('sem resultado')
  })
})

describe('Bash em background como destino da faixa e do rodapé', () => {
  const mountFocused = (item: ToolItem, focus: SubagentFocus | null) =>
    mount(BashTool, { props: { item, sessionActive: true }, global: { provide: { [SUBAGENT_FOCUS_KEY as symbol]: ref(focus) } } })

  it('o cartão se identifica e recebe foco programático só quando é de background', () => {
    const bgCard = mountFocused(bash({ background: live('running') }), null).find('[data-subagent-id="t"]')
    expect(bgCard.exists()).toBe(true)
    expect(bgCard.attributes('tabindex')).toBe('-1')
    const plain = mountFocused(bash({ input: { command: 'ls' }, background: null }), null)
    expect(plain.find('[data-subagent-id]').exists()).toBe(false)
  })

  it('destaca o cartão enquanto é o alvo', () => {
    const target = mountFocused(bash({ background: live('running') }), { id: 't', path: ['t'] }).find('[data-subagent-id="t"]')
    expect(target.attributes('data-highlighted')).toBe('true')
    const other = mountFocused(bash({ background: live('running') }), { id: 'x', path: ['x'] }).find('[data-subagent-id="t"]')
    expect(other.attributes('data-highlighted')).toBeUndefined()
  })
})
