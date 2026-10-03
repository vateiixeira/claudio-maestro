import { describe, expect, it } from 'vitest'
import type { ConversationItem } from '../../types/conversation'
import { AWAY_AFTER_SECONDS, awayCounts, shouldShowAway } from '../awayCounts'

const user = (id: string, at: number | null): ConversationItem => ({ type: 'user', id, text: id, at })
const text = (id: string, at: number | null): ConversationItem => ({ type: 'text', id, text: id, streaming: false, parent_tool_use_id: null, at })
const tool = (id: string, name: string, at: number | null, input: Record<string, unknown> = {}, parent: string | null = null): ConversationItem => ({
  type: 'tool', id, tool_use_id: id, name, input, result: null, streaming: false, parent_tool_use_id: parent, at,
})

describe('shouldShowAway', () => {
  const now = 10_000
  it('mostra quando passaram mais de 15 minutos e houve atividade depois', () => {
    expect(shouldShowAway({ lastSeenAt: now - AWAY_AFTER_SECONDS - 1, lastActivityAt: now - 60, now })).toBe(true)
  })
  it('não mostra com exatos 15 minutos nem com menos', () => {
    expect(shouldShowAway({ lastSeenAt: now - AWAY_AFTER_SECONDS, lastActivityAt: now - 60, now })).toBe(false)
    expect(shouldShowAway({ lastSeenAt: now - 60, lastActivityAt: now - 30, now })).toBe(false)
  })
  it('não mostra sem atividade depois de ter visto', () => {
    expect(shouldShowAway({ lastSeenAt: now - 3600, lastActivityAt: now - 3600, now })).toBe(false)
    expect(shouldShowAway({ lastSeenAt: now - 3600, lastActivityAt: now - 7200, now })).toBe(false)
  })
  it('não mostra quando a conversa nunca foi vista', () => {
    expect(shouldShowAway({ lastSeenAt: null, lastActivityAt: now - 60, now })).toBe(false)
    expect(shouldShowAway({ lastSeenAt: 0, lastActivityAt: now - 60, now })).toBe(false)
  })
})

describe('awayCounts', () => {
  it('conta só o que veio depois do momento', () => {
    const items = [
      user('u1', 100), tool('t1', 'Bash', 110), tool('t2', 'Edit', 120, { file_path: '/p/a.py' }),
      user('u2', 500), tool('t3', 'Read', 510), tool('t4', 'Write', 520, { file_path: '/p/b.py' }),
      tool('t5', 'Edit', 530, { file_path: '/p/b.py' }), text('x', 540),
    ]
    expect(awayCounts(items, 300)).toEqual({ turns: 1, actions: 3, files: 1 })
  })

  it('o turno que já estava em andamento e continuou conta como um', () => {
    const items = [user('u1', 100), tool('t1', 'Bash', 110), tool('t2', 'Bash', 400), text('x', 410)]
    expect(awayCounts(items, 300)).toEqual({ turns: 1, actions: 1, files: 0 })
  })

  it('aviso criado ao carregar (ex.: "Interrompida") não conta como turno nem como ação', () => {
    const notice: ConversationItem = { type: 'notice', id: 'n', level: 'warning', text: 'Interrompida', at: 900 }
    expect(awayCounts([user('u1', 100), text('a', 110), notice], 300)).toEqual({ turns: 0, actions: 0, files: 0 })
  })

  it('aviso no meio do turno novo não conta a mais', () => {
    const notice: ConversationItem = { type: 'notice', id: 'n', level: 'info', text: 'x', at: 450 }
    expect(awayCounts([user('u1', 400), notice, tool('t', 'Bash', 460)], 300)).toEqual({ turns: 1, actions: 1, files: 0 })
  })

  it('conta cada pedido novo como um turno', () => {
    const items = [user('u1', 100), text('a', 110), user('u2', 400), text('b', 410), user('u3', 500), text('c', 510)]
    expect(awayCounts(items, 300).turns).toBe(2)
  })

  it('arquivos são os file_path distintos das ferramentas de edição', () => {
    const items = [
      tool('t1', 'Edit', 400, { file_path: '/p/a.py' }), tool('t2', 'MultiEdit', 410, { file_path: '/p/a.py' }),
      tool('t3', 'Write', 420, { file_path: '/p/c.py' }), tool('t4', 'Read', 430, { file_path: '/p/d.py' }),
      tool('t5', 'Edit', 440, {}),
    ]
    expect(awayCounts(items, 300).files).toBe(2)
  })

  it('inclui o trabalho dos subagentes e ignora listas de tarefas e perguntas', () => {
    const items = [
      tool('ag', 'Agent', 400), tool('in1', 'Grep', 410, {}, 'ag'), tool('in2', 'Read', 420, {}, 'ag'),
      tool('td', 'TodoWrite', 430), tool('q', 'AskUserQuestion', 440), tool('p', 'ExitPlanMode', 450),
    ]
    expect(awayCounts(items, 300).actions).toBe(3)
  })

  it('itens sem horário não entram', () => {
    const items = [user('u1', null), tool('t1', 'Bash', null), tool('t2', 'Bash', undefined as unknown as null)]
    expect(awayCounts(items, 300)).toEqual({ turns: 0, actions: 0, files: 0 })
  })

  it('sem itens, tudo zero', () => {
    expect(awayCounts([], 300)).toEqual({ turns: 0, actions: 0, files: 0 })
  })
})
