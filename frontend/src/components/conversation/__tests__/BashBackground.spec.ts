import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
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
    expect(el.find('[data-test="bash-background-dot"]').classes()).toContain('animate-pulse')
    expect(el.find('[data-test="bash-background-dot"]').classes()).toContain('motion-reduce:animate-none')
  })

  it('concluído, falhou e parado', () => {
    expect(badge(bash({ background: live('completed') })).text()).toContain('Concluído')
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

  it('antes do resultado continua "rodando…"; sem selo duplicado no cabeçalho', () => {
    const w = mount(BashTool, { props: { item: bash({ result: null, background: null }), sessionActive: true } })
    expect(w.find('[data-test="bash-header"]').text()).toContain('rodando')
  })

  it('o selo é o único estado no cabeçalho depois do resultado', () => {
    const w = mount(BashTool, { props: { item: bash({ background: live('running') }), sessionActive: true } })
    const header = w.find('[data-test="bash-header"]').text()
    expect(header).toContain('Em background')
    expect(header).not.toContain('rodando')
    expect(header).not.toContain('sem resultado')
  })
})
