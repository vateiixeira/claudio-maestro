import { describe, expect, it } from 'vitest'
import { findLastMessage, normalizeForSearch } from '../find'
import type { ConversationItem } from '../../types/conversation'

const user = (id: string, text: string): ConversationItem => ({ type: 'user', id, text })
const text = (id: string, t: string, parent: string | null = null): ConversationItem => ({
  type: 'text', id, text: t, streaming: false, parent_tool_use_id: parent,
})
const thinking = (id: string, t: string): ConversationItem => ({
  type: 'thinking', id, text: t, streaming: false, parent_tool_use_id: null,
})

describe('normalizeForSearch', () => {
  it('tira acentos e caixa e junta os espaços', () => {
    expect(normalizeForSearch('  Ação   RÁPIDA\n\tagora ')).toBe('acao rapida agora')
  })
})

describe('findLastMessage', () => {
  const items = [
    user('u1', 'Como crio a jornada?'),
    text('a1', 'Na jornada do funil você monta uma regra'),
    user('u2', 'obrigado'),
    text('a2', 'De nada'),
  ]

  it('devolve o id da última mensagem que contém o termo, sem diferenciar acento nem caixa', () => {
    expect(findLastMessage(items, 'JORNADA')).toBe('a1')
    expect(findLastMessage(items, 'voce monta')).toBe('a1')
  })

  it('acha mensagem do usuário também', () => {
    expect(findLastMessage(items, 'obrigado')).toBe('u2')
  })

  it('ignora o texto de subagentes e o raciocínio', () => {
    const list = [
      user('u1', 'oi'),
      text('a1', 'termo raro no subagente', 'tu-1'),
      thinking('t1', 'termo raro pensado'),
    ]
    expect(findLastMessage(list, 'termo raro')).toBeNull()
  })

  it('devolve null quando nada contém o termo ou o termo é vazio', () => {
    expect(findLastMessage(items, 'inexistente')).toBeNull()
    expect(findLastMessage(items, '   ')).toBeNull()
    expect(findLastMessage([], 'jornada')).toBeNull()
  })
})
