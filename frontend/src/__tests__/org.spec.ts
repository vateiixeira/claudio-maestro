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
  agentRunFocus,
  agentState,
  formatRunDate,
  slugify,
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

describe('slugify', () => {
  it('sugere o identificador a partir do nome', () => {
    expect(slugify('Agente do Sentry')).toBe('agente-do-sentry')
    expect(slugify('  Revisão de PRs!! ')).toBe('revisao-de-prs')
    expect(slugify('---a--b---')).toBe('a-b')
  })

  it('corta no limite do backend sem terminar em hífen', () => {
    const slug = slugify('a'.repeat(39) + ' b')
    expect(slug.length).toBeLessThanOrEqual(SLUG_MAX_LENGTH)
    expect(slug.endsWith('-')).toBe(false)
  })

  it('devolve vazio quando não sobra nada', () => {
    expect(slugify('!!!')).toBe('')
  })
})

describe('formatRunDate', () => {
  const now = new Date(2026, 9, 28, 12, 0)
  it('mostra dia, mês abreviado e hora, sem o ano corrente', () => {
    expect(formatRunDate(new Date(2026, 9, 28, 14, 5).getTime() / 1000, now)).toBe('28 out 14:05')
  })

  it('acrescenta o ano quando não é o corrente', () => {
    expect(formatRunDate(new Date(2025, 0, 3, 9, 7).getTime() / 1000, now)).toBe('3 jan 2025 09:07')
  })
})

describe('agentRunFocus', () => {
  const main = makeSession({ session_id: 'main', agent_id: 1, state: 'closed' })
  const agent = (over = {}) => makeAgent({ id: 1, main_session_id: 'main', busy: true, ...over })

  it('aponta a sessão do run em andamento, com o título dela', () => {
    const run = makeSession({ session_id: 'run', agent_id: 1, title: 'Rotina da manhã', state: 'running' })
    const focus = agentRunFocus(agent({ last_run: makeRun({ outcome: 'running', session_id: 'run' }) }), [main, run])
    expect(focus).toEqual({ sessionId: 'run', title: 'Rotina da manhã', waiting: false })
  })

  it('não mostra nada com o run ainda sem sessão', () => {
    const other = makeSession({ session_id: 'other', agent_id: 1, state: 'running' })
    expect(agentRunFocus(agent({ last_run: makeRun({ outcome: 'starting', session_id: null }) }), [main, other])).toBeNull()
  })

  it('sem run ativo, aponta a sessão do agente com turno aberto', () => {
    const open = makeSession({ session_id: 'open', agent_id: 1, title: 'Tarefa 7', state: 'connecting' })
    const closed = makeSession({ session_id: 'closed', agent_id: 1, state: 'closed' })
    const foreign = makeSession({ session_id: 'foreign', agent_id: 2, state: 'running' })
    expect(agentRunFocus(agent({ last_run: makeRun({ outcome: 'concluded', session_id: 'closed' }) }), [main, closed, foreign, open]))
      .toEqual({ sessionId: 'open', title: 'Tarefa 7', waiting: false })
  })

  it('a conversa principal com turno aberto não conta', () => {
    const busyMain = makeSession({ session_id: 'main', agent_id: 1, state: 'running' })
    expect(agentRunFocus(agent(), [busyMain])).toBeNull()
  })

  it('o run que roda na própria principal não vira faixa', () => {
    const busyMain = makeSession({ session_id: 'main', agent_id: 1, state: 'running' })
    expect(agentRunFocus(agent({ last_run: makeRun({ outcome: 'running', session_id: 'main' }) }), [busyMain])).toBeNull()
  })

  it('com várias sessões abertas, pega a de atividade mais recente', () => {
    const older = makeSession({ session_id: 'older', agent_id: 1, state: 'running', last_activity_at: 100 })
    const newer = makeSession({ session_id: 'newer', agent_id: 1, state: 'running', last_activity_at: 200 })
    expect(agentRunFocus(agent(), [older, newer, main])?.sessionId).toBe('newer')
  })

  it('o run ativo vence a sessão com turno aberto', () => {
    const run = makeSession({ session_id: 'run', agent_id: 1, state: 'closed', last_activity_at: 1 })
    const open = makeSession({ session_id: 'open', agent_id: 1, state: 'running', last_activity_at: 999 })
    expect(agentRunFocus(agent({ last_run: makeRun({ outcome: 'running', session_id: 'run' }) }), [open, run])?.sessionId).toBe('run')
  })

  it('espera você quando a sessão tem pergunta ou permissão pendente', () => {
    const asking = makeSession({ session_id: 'run', agent_id: 1, state: 'running', pending_kind: 'question' })
    expect(agentRunFocus(agent({ last_run: makeRun({ outcome: 'running', session_id: 'run' }) }), [asking])?.waiting).toBe(true)
  })

  it('espera você quando a sessão aguarda uma decisão', () => {
    const asking = makeSession({ session_id: 'open', agent_id: 1, state: 'awaiting_decision' })
    expect(agentRunFocus(agent(), [asking])).toEqual(expect.objectContaining({ sessionId: 'open', waiting: true }))
  })

  it('espera você quando o run está em waiting, mesmo sem a sessão na lista', () => {
    const focus = agentRunFocus(agent({ last_run: makeRun({ outcome: 'waiting', session_id: 'gone' }) }), [main])
    expect(focus).toEqual(expect.objectContaining({ sessionId: 'gone', waiting: true }))
  })

  it('usa um título de reserva, pela origem do run, quando a sessão não está na lista', () => {
    const focus = agentRunFocus(agent({ last_run: makeRun({ outcome: 'running', source: 'routine', session_id: 'gone' }) }), [main])
    expect(focus).toEqual({ sessionId: 'gone', title: 'Execução de rotina', waiting: false })
  })

  it('usa a reserva da origem quando a sessão do run tem título vazio', () => {
    const run = makeSession({ session_id: 'run', agent_id: 1, title: '', state: 'running' })
    const focus = agentRunFocus(agent({ last_run: makeRun({ outcome: 'running', source: 'assignment', session_id: 'run' }) }), [main, run])
    expect(focus?.title).toBe('Execução de tarefa')
  })

  it('usa "Conversa sem título" quando a sessão com turno aberto tem título vazio', () => {
    const open = makeSession({ session_id: 'open', agent_id: 1, title: '', state: 'running' })
    expect(agentRunFocus(agent(), [main, open])).toEqual({ sessionId: 'open', title: 'Conversa sem título', waiting: false })
  })

  it('sem run nem turno aberto, não há faixa', () => {
    const closed = makeSession({ session_id: 'closed', agent_id: 1, state: 'closed' })
    expect(agentRunFocus(agent({ busy: false, last_run: makeRun({ outcome: 'concluded', session_id: 'closed' }) }), [main, closed])).toBeNull()
    expect(agentRunFocus(agent({ busy: false, last_run: null }), [])).toBeNull()
  })
})
