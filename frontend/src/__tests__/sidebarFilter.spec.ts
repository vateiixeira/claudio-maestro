import { describe, expect, it } from 'vitest'
import { matchesSidebarFilter, sidebarFilter, sidebarFilterLabel } from '../sidebarFilter'
import { makeSession } from '../test/factories'

describe('sidebarFilterLabel', () => {
  it('escreve a contagem e o nome do filtro', () => {
    expect(sidebarFilterLabel('running', 4)).toBe('4 rodando')
    expect(sidebarFilterLabel('waiting', 2)).toBe('2 aguardando você')
    expect(sidebarFilterLabel('unread', 1)).toBe('1 não lida')
    expect(sidebarFilterLabel('unread', 5)).toBe('5 não lidas')
  })
})

describe('matchesSidebarFilter', () => {
  it('sem filtro aceita tudo', () => {
    expect(matchesSidebarFilter(makeSession({ display_state: 'running' }), null)).toBe(true)
    expect(matchesSidebarFilter(makeSession({ display_state: 'finished' }), null)).toBe(true)
  })

  it('rodando: só a que está em execução', () => {
    expect(matchesSidebarFilter(makeSession({ display_state: 'running' }), 'running')).toBe(true)
    expect(matchesSidebarFilter(makeSession({ display_state: 'waiting', unread: true }), 'running')).toBe(false)
  })

  it('aguardando você: só a espera que pede você, não a comum', () => {
    expect(matchesSidebarFilter(makeSession({ display_state: 'waiting', unread: true }), 'waiting')).toBe(true)
    expect(matchesSidebarFilter(makeSession({ display_state: 'waiting', unread: false, pending_kind: 'plan' }), 'waiting')).toBe(true)
    expect(matchesSidebarFilter(makeSession({ display_state: 'waiting', unread: false }), 'waiting')).toBe(false)
    expect(matchesSidebarFilter(makeSession({ display_state: 'running', unread: true }), 'waiting')).toBe(false)
  })

  it('não lidas: a que tem novidade', () => {
    expect(matchesSidebarFilter(makeSession({ unread: true }), 'unread')).toBe(true)
    expect(matchesSidebarFilter(makeSession({ unread: false }), 'unread')).toBe(false)
  })
})

describe('sidebarFilter', () => {
  it('começa desligado', () => {
    expect(sidebarFilter.value).toBeNull()
  })
})
