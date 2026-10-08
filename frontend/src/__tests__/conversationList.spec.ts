import { describe, expect, it } from 'vitest'
import { dateLabel, groupByDate, inInbox, INBOX_TABS, isInboxTab, waitingReason } from '../conversationList'
import { makeSession } from '../test/factories'

const at = (y: number, m: number, d: number, hh = 12, mm = 0) => new Date(y, m - 1, d, hh, mm).getTime() / 1000

describe('motivo da espera', () => {
  it('só existe para quem aguarda o usuário', () => {
    expect(waitingReason(makeSession({ display_state: 'running' }))).toBeNull()
    expect(waitingReason(makeSession({ display_state: 'finished' }))).toBeNull()
  })

  it('mostra erro, permissão, pergunta, plano ou sua vez', () => {
    expect(waitingReason(makeSession({ display_state: 'waiting', state: 'error' }))).toBe('Parou com erro')
    expect(waitingReason(makeSession({
      display_state: 'waiting', state: 'awaiting_decision', pending_kind: 'tool',
      pending_permission: { prompt_id: 'p', tool_name: 'Bash', summary: 'ls', can_allow_always: false },
    }))).toBe('Pede permissão: Bash')
    expect(waitingReason(makeSession({ display_state: 'waiting', state: 'awaiting_decision', pending_kind: 'question' }))).toBe('Fez uma pergunta')
    expect(waitingReason(makeSession({ display_state: 'waiting', state: 'awaiting_decision', pending_kind: 'plan' }))).toBe('Plano para aprovar')
    expect(waitingReason(makeSession({ display_state: 'waiting', state: 'idle' }))).toBe('Sua vez')
  })
})

describe('abas da Inbox', () => {
  const waiting = makeSession({ session_id: 'w', display_state: 'waiting', pending_kind: 'plan' })
  const plainWait = makeSession({ session_id: 'pw', display_state: 'waiting', state: 'idle' })
  const errored = makeSession({ session_id: 'e', display_state: 'waiting', state: 'error' })
  const running = makeSession({ session_id: 'r', display_state: 'running' })
  const unreadOpen = makeSession({ session_id: 'u', display_state: 'running', unread: true })
  const finishedUnread = makeSession({ session_id: 'fu', display_state: 'finished', unread: true })
  const finishedRead = makeSession({ session_id: 'f', display_state: 'finished' })
  const all = [waiting, plainWait, errored, running, unreadOpen, finishedUnread, finishedRead]
  const ids = (tab: Parameters<typeof inInbox>[1]) => all.filter((s) => inInbox(s, tab)).map((s) => s.session_id)

  it('a aba pede-voce mantém o id e se chama "Aguardando você"', () => {
    expect(INBOX_TABS[0]).toEqual({ id: 'pede-voce', label: 'Aguardando você' })
  })

  it('separa por aba e nunca mostra finalizadas', () => {
    expect(ids('pede-voce')).toEqual(['w', 'e'])
    expect(ids('nao-lidas')).toEqual(['u'])
    expect(ids('em-execucao')).toEqual(['r', 'u'])
    expect(ids('todas')).toEqual(['w', 'pw', 'e', 'r', 'u'])
  })

  it('pode-fechar lista as abertas que podem ser fechadas', () => {
    const open = makeSession({ display_state: 'waiting', closure_verdict: 'can_close' })
    expect(inInbox(open, 'pode-fechar')).toBe(true)
    expect(inInbox({ ...open, closure_verdict: 'user_action' }, 'pode-fechar')).toBe(false)
    expect(inInbox({ ...open, display_state: 'finished' }, 'pode-fechar')).toBe(false)
    expect(inInbox({ ...open, display_state: 'running' }, 'pode-fechar')).toBe(false)
    expect(INBOX_TABS.find((t) => t.id === 'pode-fechar')?.label).toBe('Pode fechar')
    expect(isInboxTab('pode-fechar')).toBe(true)
  })

  it('reconhece as abas válidas', () => {
    expect(isInboxTab('nao-lidas')).toBe(true)
    expect(isInboxTab('outra')).toBe(false)
    expect(isInboxTab(undefined)).toBe(false)
  })
})

describe('grupos por data', () => {
  const now = new Date(2026, 8, 29, 0, 20)

  it('usa o dia local, inclusive perto da meia-noite', () => {
    expect(dateLabel(at(2026, 9, 29, 0, 10), now, false)).toBe('Hoje')
    expect(dateLabel(at(2026, 9, 28, 23, 50), now, false)).toBe('Ontem')
    expect(dateLabel(at(2026, 9, 27), now, false)).toBe('Antes')
  })

  it('tem "Esta semana" só quando pedido', () => {
    expect(dateLabel(at(2026, 9, 24), now, true)).toBe('Esta semana')
    expect(dateLabel(at(2026, 9, 22), now, true)).toBe('Antes')
    expect(dateLabel(at(2026, 9, 24), now, false)).toBe('Antes')
  })

  it('agrupa mantendo a ordem e omitindo grupos vazios', () => {
    const list = [
      makeSession({ session_id: 'a', last_activity_at: at(2026, 9, 29, 0, 5) }),
      makeSession({ session_id: 'b', last_activity_at: at(2026, 9, 20) }),
    ]
    expect(groupByDate(list, now, true).map((g) => [g.label, g.sessions.map((s) => s.session_id)])).toEqual([
      ['Hoje', ['a']],
      ['Antes', ['b']],
    ])
  })
})

describe('Inbox com marcações', () => {
  const waitingUnread = { display_state: 'waiting' as const, unread: true }
  it('Aguardando você deixa de fora em espera, bloqueada e para revisar sem pedido', () => {
    expect(inInbox(makeSession({ ...waitingUnread, mark: 'on_hold' }), 'pede-voce')).toBe(false)
    expect(inInbox(makeSession({ ...waitingUnread, mark: 'blocked' }), 'pede-voce')).toBe(false)
    expect(inInbox(makeSession({ ...waitingUnread, mark: 'review' }), 'pede-voce')).toBe(false)
  })
  it('pedido do Claude volta para Aguardando você mesmo marcada', () => {
    expect(inInbox(makeSession({ display_state: 'waiting', mark: 'on_hold', pending_kind: 'question' }), 'pede-voce')).toBe(true)
  })
  it('Não lidas deixa de fora só o que está em Depois', () => {
    expect(inInbox(makeSession({ ...waitingUnread, mark: 'on_hold' }), 'nao-lidas')).toBe(false)
    expect(inInbox(makeSession({ ...waitingUnread, mark: 'review' }), 'nao-lidas')).toBe(true)
  })
  it('abas Para revisar e Depois', () => {
    expect(inInbox(makeSession({ mark: 'review' }), 'para-revisar')).toBe(true)
    expect(inInbox(makeSession({ mark: 'on_hold' }), 'depois')).toBe(true)
    expect(inInbox(makeSession({ mark: 'blocked' }), 'depois')).toBe(true)
    expect(inInbox(makeSession({ mark: 'on_hold' }), 'para-revisar')).toBe(false)
    expect(inInbox(makeSession(), 'depois')).toBe(false)
  })
  it('Todas inclui as marcadas', () => {
    expect(inInbox(makeSession({ display_state: 'waiting', mark: 'on_hold' }), 'todas')).toBe(true)
  })
  it('a ordem das abas', () => {
    expect(INBOX_TABS.map((t) => t.label)).toEqual(['Aguardando você', 'Não lidas', 'Em execução', 'Para revisar', 'Pode fechar', 'Depois', 'Todas'])
  })
})

describe('sessões descartadas', () => {
  it('não entram em nenhuma aba da Inbox, nem em Todas', () => {
    const s = makeSession({ mark: 'discarded', display_state: 'waiting', state: 'awaiting_decision', pending_kind: 'tool', unread: true })
    for (const tab of INBOX_TABS) expect(inInbox(s, tab.id)).toBe(false)
  })
})
