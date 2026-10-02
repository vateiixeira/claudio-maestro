import { describe, expect, it } from 'vitest'
import { backgroundState } from '../background'
import type { ToolItem } from '../../types/conversation'

function bash(input: Record<string, unknown>, background?: ToolItem['background']): ToolItem {
  return { type: 'tool', id: 't', tool_use_id: 'tu', name: 'Bash', input, result: null, streaming: false, parent_tool_use_id: null, background }
}

describe('estado de Bash em background', () => {
  it('comando comum não tem estado', () => {
    expect(backgroundState(bash({ command: 'ls' }))).toBeNull()
    expect(backgroundState(bash({ command: 'ls', run_in_background: false }))).toBeNull()
  })

  it('usa o status ao vivo quando existe', () => {
    for (const status of ['running', 'completed', 'failed', 'stopped'] as const) {
      expect(backgroundState(bash({ command: 'x', run_in_background: true }, { task_id: 'b1', status, summary: null }))).toBe(status)
    }
  })

  it('sem status ao vivo mas pedido em background, o rótulo é neutro', () => {
    expect(backgroundState(bash({ command: 'x', run_in_background: true }))).toBe('unknown')
    expect(backgroundState(bash({ command: 'x', run_in_background: true }, null))).toBe('unknown')
  })

  it('outras ferramentas não têm estado', () => {
    const item = { ...bash({ run_in_background: true }), name: 'Read' }
    expect(backgroundState(item)).toBeNull()
  })
})
