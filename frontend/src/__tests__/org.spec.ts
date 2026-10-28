import { describe, expect, it } from 'vitest'
import {
  AGENT_STATE_LABELS,
  DAYS,
  DEFINITION_MAX_BYTES,
  MEMORY_MAX,
  OUTCOME_LABELS,
  PRIORITY_LABELS,
  SLUG_MAX_LENGTH,
  SOURCE_LABELS,
  TASK_STATUS_LABELS,
  agentState,
  outcomeShape,
  taskStatusShape,
} from '../org'
import { makeAgent, makeRun, makeSession } from '../test/factories'

describe('agentState', () => {
  it('prioriza desligado, depois aguardando, depois executando', () => {
    const main = makeSession({ session_id: 'main', agent_id: 1, pending_kind: 'tool' })
    // desligado vence tudo, até a espera e a execução
    expect(agentState(makeAgent({ enabled: false, busy: true, main_session_id: 'main' }), [main])).toBe('off')
    // aguardando vence executando
    expect(agentState(makeAgent({ busy: true, main_session_id: 'main' }), [main])).toBe('waiting')
    expect(agentState(makeAgent({ busy: true }), [])).toBe('busy')
    expect(agentState(makeAgent({ busy: false }), [])).toBe('idle')
  })

  it('aguardando vem da conversa principal pedindo decisão ou da última execução esperando', () => {
    const agent = makeAgent({ main_session_id: 'main' })
    expect(agentState(agent, [makeSession({ session_id: 'main', state: 'awaiting_decision' })])).toBe('waiting')
    expect(agentState(agent, [makeSession({ session_id: 'main', pending_kind: 'question' })])).toBe('waiting')
    expect(agentState(agent, [makeSession({ session_id: 'main' })])).toBe('idle')
    // a espera de outra sessão não conta
    expect(agentState(agent, [makeSession({ session_id: 'outra', pending_kind: 'tool' })])).toBe('idle')
    expect(agentState(makeAgent({ last_run: makeRun({ outcome: 'waiting' }) }), [])).toBe('waiting')
    expect(agentState(makeAgent({ last_run: makeRun({ outcome: 'concluded' }) }), [])).toBe('idle')
  })

  it('uma sessão principal terminada não deixa o agente aguardando', () => {
    const agent = makeAgent({ main_session_id: 'main' })
    expect(agentState(agent, [makeSession({ session_id: 'main', pending_kind: 'tool', display_state: 'finished' })])).toBe('idle')
  })
})

describe('rótulos e formas', () => {
  it('usa os rótulos fixos em português', () => {
    expect(TASK_STATUS_LABELS).toEqual({
      todo: 'A fazer', in_progress: 'Em andamento', in_review: 'Em revisão',
      blocked: 'Bloqueada', done: 'Concluída', cancelled: 'Cancelada',
    })
    expect(PRIORITY_LABELS).toEqual({ urgent: 'Urgente', high: 'Alta', normal: 'Normal', low: 'Baixa' })
    expect(AGENT_STATE_LABELS).toEqual({ idle: 'Ocioso', busy: 'Executando', waiting: 'Aguardando você', off: 'Desligado' })
    expect(SOURCE_LABELS).toEqual({
      routine: 'Rotina', message: 'Mensagem', assignment: 'Tarefa',
      comment: 'Comentário', decision: 'Decisão', manual: 'Manual',
    })
  })

  it('os resultados de execução não têm "queued"', () => {
    expect(Object.keys(OUTCOME_LABELS).sort()).toEqual(
      ['cancelled', 'closed', 'concluded', 'failed', 'missed', 'running', 'skipped', 'starting', 'waiting'],
    )
    expect(OUTCOME_LABELS.waiting).toBe('Esperando você')
    expect(OUTCOME_LABELS.running).toBe('Rodando')
  })

  it('todo estado tem uma forma além da cor', () => {
    expect(outcomeShape('running')).toBe('spinner')
    expect(outcomeShape('starting')).toBe('spinner')
    expect(outcomeShape('concluded')).toBe('check')
    expect(outcomeShape('closed')).toBe('check')
    expect(outcomeShape('waiting')).toBe('triangle')
    expect(outcomeShape('failed')).toBe('cross')
    expect(outcomeShape('skipped')).toBe('dash')
    expect(outcomeShape('cancelled')).toBe('dash')
    expect(taskStatusShape('todo')).toBe('circle')
    expect(taskStatusShape('in_progress')).toBe('spinner')
    expect(taskStatusShape('in_review')).toBe('triangle')
    expect(taskStatusShape('blocked')).toBe('cross')
    expect(taskStatusShape('done')).toBe('check')
    expect(taskStatusShape('cancelled')).toBe('dash')
  })

  it('espelha os limites do backend', () => {
    expect(SLUG_MAX_LENGTH).toBe(40)
    expect(MEMORY_MAX).toBe(4000)
    expect(DEFINITION_MAX_BYTES).toBe(100_000)
    expect(DAYS.map((d) => d.digit).join('')).toBe('1234567')
  })
})
