import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ActionGroup from '../ActionGroup.vue'
import ConversationBlock from '../ConversationBlock.vue'
import RailNode from '../RailNode.vue'
import type { ToolItem } from '../../../types/conversation'

// Green means done; amber (secondary) means working.

const tool = (name: string, input: Record<string, unknown> = {}, extra: Partial<ToolItem> = {}): ToolItem =>
  ({
    type: 'tool', id: `t-${name}`, tool_use_id: `tu-${name}`, name, input,
    result: null, streaming: false, parent_tool_use_id: null, ...extra,
  }) as ToolItem

function runningBlock(item: ToolItem) {
  return mount(ConversationBlock, { props: { item, sessionActive: true } })
}

describe('indicadores de rodando em âmbar', () => {
  it('trilha: bolinha rodando é âmbar e pulsa', () => {
    const cls = mount(RailNode, { props: { kind: 'running' } }).find('[data-test="rail-dot"]').classes()
    expect(cls).toEqual(expect.arrayContaining(['bg-secondary', 'animate-pulse', 'motion-reduce:animate-none']))
    expect(cls).not.toContain('bg-primary')
  })

  it('Bash: o estado rodando é âmbar e gira; concluído segue verde', () => {
    const running = runningBlock(tool('Bash', { command: 'ls' })).find('[data-test="work-status"]')
    expect(running.attributes('data-status')).toBe('running')
    expect(running.find('svg').classes()).toEqual(expect.arrayContaining(['text-secondary-soft', 'animate-spin']))
    expect(running.find('svg').classes()).not.toContain('text-primary')
    const done = mount(ConversationBlock, {
      props: { item: tool('Bash', { command: 'ls' }, { result: { content: 'ok', is_error: false, details: null } }), sessionActive: false },
    }).find('[data-test="work-status"]')
    expect(done.attributes('data-status')).toBe('ok')
    expect(done.find('svg').classes()).toContain('text-primary')
  })

  it.each([
    ['Read', { file_path: '/a' }],
    ['Grep', { pattern: 'x' }],
    ['WebFetch', { url: 'x' }],
    ['Edit', { file_path: '/a', old_string: 'a', new_string: 'b' }],
    ['NotebookEdit', { notebook_path: '/a' }],
  ])('%s: o giro de andamento é âmbar, com "rodando…" para leitor de tela', (name, input) => {
    const state = runningBlock(tool(name, input)).find('[data-test="work-status"]')
    expect(state.attributes('data-status')).toBe('running')
    expect(state.find('svg').classes()).toContain('text-secondary-soft')
    expect(state.find('svg').classes()).not.toContain('text-primary-soft')
    expect(state.find('.sr-only').text()).toBe('rodando…')
  })

  it('subagente rodando: giro e última atividade em âmbar; concluído segue verde', () => {
    const sub = (status: 'running' | 'completed') => ({
      task_id: 't', subagent_type: 'x', description: 'd', status, last_activity: 'lendo coisa', usage: null, summary: null,
    })
    const running = runningBlock(tool('Agent', { description: 'd', prompt: 'p' }, { subagent: sub('running') }))
    const icon = running.find('[data-test="work-status"] svg')
    expect(icon.classes()).toEqual(expect.arrayContaining(['animate-spin', 'text-secondary-soft']))
    expect(icon.classes()).not.toContain('text-primary')
    expect(running.find('p.font-mono').classes()).toContain('text-secondary-soft')
    const done = mount(ConversationBlock, {
      props: { item: tool('Agent', { description: 'd', prompt: 'p' }, { subagent: sub('completed') }), sessionActive: false },
    })
    expect(done.find('[data-test="work-status"] svg').classes()).toContain('text-primary')
  })

  it('grupo de ações: "rodando…" na linha é âmbar', () => {
    const w = mount(ActionGroup, { props: { items: [tool('Read', { file_path: '/a' })], open: true, sessionActive: true } })
    const meta = w.find('[data-test="action-row"] span.font-mono.text-\\[0\\.6875rem\\]')
    expect(meta.text()).toBe('rodando…')
    expect(meta.classes()).toContain('text-secondary-soft')
    expect(meta.classes()).not.toContain('text-primary-soft')
  })

  it('tarefas: em andamento é âmbar, concluída verde, pendente cinza', () => {
    const tasks = [
      { id: '1', subject: 'a', status: 'pending' as const },
      { id: '2', subject: 'b', status: 'in_progress' as const },
      { id: '3', subject: 'c', status: 'completed' as const },
    ]
    const w = mount(ConversationBlock, { props: { item: tool('TodoWrite', { todos: [] }), tasks } })
    const marks = w.findAll('[data-test="task-row"] > span:first-child').map((m) => m.classes())
    expect(marks[0]).toContain('text-fg-subtle')
    expect(marks[1]).toContain('text-secondary')
    expect(marks[1]).not.toContain('text-primary')
    expect(marks[2]).toContain('text-primary')
    const update = (status: string) =>
      mount(ConversationBlock, { props: { item: tool('TaskUpdate', { taskId: '1', subject: 's', status }) } })
        .find('[data-test="task-tool"] .text-xs > span:last-child')
    expect(update('in_progress').classes()).toContain('text-secondary-soft')
    expect(update('completed').classes()).toContain('text-primary-soft')
  })
})
