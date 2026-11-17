import { describe, expect, it } from 'vitest'
import { sessionActivity } from '../rowActivity'
import { makeSession } from '../../test/factories'

const plan = { path: 'p.md', title: 'Plano', total: 5, done: 2, current: { number: 3, title: 'Revisar a tarefa' } }

describe('sessionActivity', () => {
  it('espera que pede você vira waiting', () => {
    expect(sessionActivity(makeSession({ display_state: 'waiting', state: 'awaiting_decision', pending_kind: 'plan', unread: true })))
      .toEqual({ kind: 'waiting', text: 'Plano para aprovar' })
  })

  it('espera comum não é waiting', () => {
    expect(sessionActivity(makeSession({ display_state: 'waiting', unread: false, digest_short: 'Resumo curto' })))
      .toEqual({ kind: 'summary', text: 'Resumo curto' })
  })

  it('o plano vem antes da ação', () => {
    expect(sessionActivity(makeSession({ display_state: 'running', plan, last_action: 'Bash: pnpm test' })))
      .toEqual({ kind: 'plan', text: 'Revisar a tarefa' })
  })

  it('reconhece comando, subagente e ação', () => {
    expect(sessionActivity(makeSession({ display_state: 'running', last_action: 'Bash: pnpm test' }))).toEqual({ kind: 'command', text: 'pnpm test' })
    expect(sessionActivity(makeSession({ display_state: 'running', last_action: 'Agent: Revisar o diff' }))).toEqual({ kind: 'subagent', text: 'Revisar o diff' })
    expect(sessionActivity(makeSession({ display_state: 'running', last_action: 'Task: Rodar testes' }))).toEqual({ kind: 'subagent', text: 'Rodar testes' })
    expect(sessionActivity(makeSession({ display_state: 'running', last_action: 'Edit sessions.py' }))).toEqual({ kind: 'action', text: 'Edit sessions.py' })
  })

  it('cai no resumo curto e depois em nada', () => {
    expect(sessionActivity(makeSession({ display_state: 'running', last_action: null, digest_short: 'Gerando propostas' }))).toEqual({ kind: 'summary', text: 'Gerando propostas' })
    expect(sessionActivity(makeSession({ display_state: 'finished', digest_short: null }))).toBeNull()
  })
})
