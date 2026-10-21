import { describe, expect, it } from 'vitest'
import type { ToolItem } from '../../types/conversation'
import { workCaption } from '../work'

const tool = (id: string, name: string, input: ToolItem['input'] = {}, extra: Partial<ToolItem> = {}): ToolItem => ({
  type: 'tool', id, tool_use_id: `tu-${id}`, name, input,
  result: { content: 'ok', is_error: false, details: null }, streaming: false, parent_tool_use_id: null, ...extra,
})

describe('resumo de trabalho em uma linha', () => {
  it('resume ações concluídas com verbos e o nome do arquivo lido', () => {
    expect(workCaption([
      tool('a', 'Bash'), tool('b', 'Bash'), tool('c', 'Read', { file_path: '/projeto/docs/plano.md' }),
    ], false)).toBe('Executou 2 comandos, leu plano.md')
  })

  it('conta arquivos distintos sem repetir caminhos longos', () => {
    expect(workCaption([
      tool('a', 'Read', { file_path: '/p/a.ts' }), tool('b', 'Read', { file_path: '/p/a.ts' }),
      tool('c', 'Read', { file_path: '/p/b.ts' }), tool('d', 'Edit', { file_path: '/p/a.ts' }),
    ], false)).toBe('Leu 2 arquivos, editou a.ts')
  })

  it('usa a descrição enquanto executa e troca pelo resumo ao receber o resultado', () => {
    const pending = tool('b', 'Bash', { command: 'pnpm test', description: 'Conferir dependências' }, { result: null })
    expect(workCaption([pending], true)).toBe('Conferir dependências')
    expect(workCaption([{ ...pending, result: { content: 'ok', is_error: false, details: null } }], true)).toBe('Executou 1 comando')
  })

  it('permissão e falha não somem atrás de outra ação em execução', () => {
    const pending = tool('b', 'Bash', { command: 'pnpm test' }, { result: null })
    const failed = tool('a', 'Bash', {}, { result: { content: 'erro', is_error: true, details: null } })
    expect(workCaption([failed, pending], true)).toContain('1 falhou')
    expect(workCaption([pending], true, new Set(['tu-b']))).toBe('Esperando você')
  })

  it('não apresenta ferramenta sem resultado como trabalho concluído', () => {
    expect(workCaption([tool('a', 'Read', { file_path: '/p/a.ts' }, { result: null, result_missing: true })], false)).toBe('1 ação sem resultado')
  })
})
