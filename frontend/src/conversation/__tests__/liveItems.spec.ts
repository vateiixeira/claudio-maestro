import { describe, expect, it } from 'vitest'
import { buildTurns } from '../turns'
import { FOLLOW_DISTANCE, distanceToEnd, entryKey, isNearEnd, turnKeys } from '../liveItems'
import type { ConversationItem } from '../../types/conversation'

const user = (id: string) => ({ type: 'user', id, text: id }) as ConversationItem
const text = (id: string) => ({ type: 'text', id, text: id, streaming: false, parent_tool_use_id: null }) as ConversationItem
const tool = (id: string) => ({ type: 'tool', id, tool_use_id: `tu-${id}`, name: 'Bash', input: {}, status: 'done', parent_tool_use_id: null }) as unknown as ConversationItem

describe('liveItems', () => {
  it('chaves: mensagem, itens, grupo de trabalho e pedidos', () => {
    const turns = buildTurns([user('u1'), text('a'), tool('t1'), tool('t2'), text('b')])
    const keys = turnKeys(turns, [{ prompt_id: 'p1' }])
    expect([...keys].sort()).toEqual(['a', 'b', 'group-t1', 'prompt:p1', 'u1'])
  })

  it('o grupo mantém a chave quando cresce', () => {
    const before = buildTurns([user('u1'), tool('t1')])
    const after = buildTurns([user('u1'), tool('t1'), tool('t2')])
    expect(entryKey(before[0]!.entries[0]!)).toBe(entryKey(after[0]!.entries[0]!))
  })

  it('itens antes da primeira mensagem entram', () => {
    expect([...turnKeys(buildTurns([text('a')]), [])]).toEqual(['a'])
  })

  const box = (scrollHeight: number, scrollTop: number, clientHeight: number) => ({ scrollHeight, scrollTop, clientHeight }) as HTMLElement

  it('distância até o fim', () => {
    expect(distanceToEnd(box(2000, 1500, 400))).toBe(100)
  })

  it('acompanha o fim só a menos de 80px', () => {
    expect(FOLLOW_DISTANCE).toBe(80)
    expect(isNearEnd(box(2000, 1600, 400))).toBe(true)
    expect(isNearEnd(box(2000, 1521, 400))).toBe(true)
    expect(isNearEnd(box(2000, 1520, 400))).toBe(false)
    expect(isNearEnd(box(2000, 0, 400))).toBe(false)
  })
})
