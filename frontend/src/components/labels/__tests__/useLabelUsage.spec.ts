import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useLabelUsage } from '../useLabelUsage'
import { useSessionsStore } from '../../../stores/sessions'
import { makeSession } from '../../../test/factories'

beforeEach(() => setActivePinia(createPinia()))

describe('useLabelUsage', () => {
  it('conta as conversas de todos os projetos que têm a etiqueta', () => {
    const sessions = useSessionsStore()
    sessions.loaded = true
    sessions.setForProject(1, [
      makeSession({ session_id: 'a', project_id: 1, label_ids: [1, 2] }),
      makeSession({ session_id: 'b', project_id: 1, label_ids: [1] }),
    ])
    sessions.setForProject(2, [makeSession({ session_id: 'c', project_id: 2, label_ids: [1] })])
    const usage = useLabelUsage()
    expect(usage.count(1)).toBe(3)
    expect(usage.count(2)).toBe(1)
    expect(usage.count(9)).toBe(0)
  })

  it('countText devolve "sem uso", "1 conversa" ou "N conversas"', () => {
    const sessions = useSessionsStore()
    sessions.loaded = true
    sessions.setForProject(1, [
      makeSession({ session_id: 'a', label_ids: [1, 2] }),
      makeSession({ session_id: 'b', label_ids: [1] }),
    ])
    const usage = useLabelUsage()
    expect(usage.countText(1)).toBe('2 conversas')
    expect(usage.countText(2)).toBe('1 conversa')
    expect(usage.countText(9)).toBe('sem uso')
  })

  it('acompanha as mudanças do store', () => {
    const sessions = useSessionsStore()
    sessions.loaded = true
    sessions.setForProject(1, [makeSession({ session_id: 'a', label_ids: [] })])
    const usage = useLabelUsage()
    expect(usage.countText(1)).toBe('sem uso')
    sessions.setForProject(1, [makeSession({ session_id: 'a', label_ids: [1] })])
    expect(usage.countText(1)).toBe('1 conversa')
  })

  it('enquanto as conversas não carregaram, ready é falso e countText fica vazio', () => {
    const sessions = useSessionsStore()
    sessions.setForProject(1, [makeSession({ session_id: 'a', label_ids: [1] })])
    const usage = useLabelUsage()
    expect(usage.ready.value).toBe(false)
    expect(usage.countText(1)).toBe('')
    expect(usage.countText(9)).toBe('')
    sessions.loaded = true
    expect(usage.ready.value).toBe(true)
    expect(usage.countText(1)).toBe('1 conversa')
    expect(usage.countText(9)).toBe('sem uso')
  })

  it('ignora sessões sem label_ids', () => {
    const sessions = useSessionsStore()
    sessions.setForProject(1, [makeSession({ session_id: 'a', label_ids: undefined })])
    expect(useLabelUsage().count(1)).toBe(0)
  })
})
