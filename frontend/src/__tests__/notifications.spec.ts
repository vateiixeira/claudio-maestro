import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick } from 'vue'
import { FakeAudioContext, FakeNotification, installFakeNotification } from '../test/fakeNotification'
import { makeSession } from '../test/factories'
import { useSessionsStore } from '../stores/sessions'
import { notificationPrefs, setNotificationPref, DEFAULT_NOTIFICATION_PREFS } from '../notificationPrefs'
import {
  bindNotifications,
  notificationPermission,
  notifySession,
  playAlertSound,
  reasonOf,
  refreshNotificationPermission,
  requestNotificationPermission,
  sendTestNotification,
  snapshotOf,
  transitionKind,
} from '../notifications'

function setHidden(hidden: boolean) {
  Object.defineProperty(document, 'hidden', { value: hidden, configurable: true })
}

beforeEach(() => {
  localStorage.clear()
  notificationPrefs.value = { ...DEFAULT_NOTIFICATION_PREFS }
  setHidden(true)
  FakeAudioContext.created = []
})
afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  setHidden(false)
})

const asking = (extra = {}) => makeSession({ state: 'awaiting_decision', display_state: 'waiting', pending_kind: 'tool', pending_permission: { prompt_id: 'p1', tool_name: 'Bash', summary: 'pnpm test', can_allow_always: true }, ...extra })
const idle = (extra = {}) => makeSession({ state: 'idle', display_state: 'waiting', ...extra })
const running = (extra = {}) => makeSession({ state: 'running', display_state: 'running', ...extra })

describe('transição que dispara', () => {
  it.each([
    ['permissão', asking(), 'permission'],
    ['pergunta', asking({ pending_kind: 'question', pending_permission: null }), 'question'],
    ['plano', asking({ pending_kind: 'plan', pending_permission: null }), 'plan'],
  ] as const)('entrar em %s dispara o tipo certo', (_name, next, kind) => {
    expect(transitionKind(snapshotOf(running()), snapshotOf(next))).toBe(kind)
  })

  it('o pedido só conta quando o motivo chega, e uma vez', () => {
    // `session.state` chega antes de `pending_kind`: ainda não dá para dizer o que é.
    const early = idle({ state: 'awaiting_decision', pending_kind: null, unread: false })
    expect(transitionKind(snapshotOf(running()), snapshotOf(early))).toBeNull()
    expect(transitionKind(snapshotOf(early), snapshotOf(asking()))).toBe('permission')
    expect(transitionKind(snapshotOf(asking()), snapshotOf(asking({ last_activity_at: 9 })))).toBeNull()
  })

  it('um segundo pedido de permissão na mesma conversa dispara de novo', () => {
    const second = asking({ pending_permission: { prompt_id: 'p2', tool_name: 'Bash', summary: 'ls', can_allow_always: true } })
    expect(transitionKind(snapshotOf(asking()), snapshotOf(second))).toBe('permission')
  })

  it('turno concluído com novidade não vista dispara "finished"', () => {
    expect(transitionKind(snapshotOf(running()), snapshotOf(idle({ unread: true })))).toBe('finished')
  })

  it('parar com erro dispara "finished"', () => {
    expect(transitionKind(snapshotOf(running()), snapshotOf(makeSession({ state: 'error', display_state: 'waiting', error: 'x' })))).toBe('finished')
  })

  it('não dispara: sem mudança, saindo do pedido, marcada, ou sem conhecer a anterior', () => {
    expect(transitionKind(snapshotOf(idle()), snapshotOf(idle()))).toBeNull()
    expect(transitionKind(snapshotOf(asking()), snapshotOf(running()))).toBeNull()
    // Responder o pedido e já ficar parada não é novidade.
    expect(transitionKind(snapshotOf(asking()), snapshotOf(idle({ unread: true })))).toBeNull()
    // Marcada, a novidade não pede você.
    expect(transitionKind(snapshotOf(running()), snapshotOf(idle({ unread: true, mark: 'on_hold' })))).toBeNull()
    // Terminou mas já foi vista.
    expect(transitionKind(snapshotOf(running()), snapshotOf(idle({ unread: false })))).toBeNull()
    expect(transitionKind(undefined, snapshotOf(asking()))).toBeNull()
  })

  it('marcada ainda dispara com um pedido real', () => {
    expect(transitionKind(snapshotOf(running({ mark: 'review' })), snapshotOf(asking({ mark: 'review' })))).toBe('permission')
  })
})

describe('texto do aviso', () => {
  it('descreve o motivo numa frase', () => {
    expect(reasonOf('permission', asking())).toBe('Pede permissão para rodar `pnpm test`')
    expect(reasonOf('permission', asking({ pending_permission: null }))).toBe('Pede permissão')
    expect(reasonOf('question', asking())).toBe('Fez uma pergunta')
    expect(reasonOf('plan', asking())).toBe('Plano para aprovar')
    expect(reasonOf('finished', idle())).toBe('Concluiu o turno')
    expect(reasonOf('finished', makeSession({ state: 'error' }))).toBe('Parou com erro')
    expect(reasonOf('subagent', idle())).toBe('Um subagente falhou')
  })
})

describe('texto do pedido de permissão (o `summary` do backend)', () => {
  const perm = (tool_name: string, summary: string) =>
    asking({ pending_permission: { prompt_id: 'x', tool_name, summary, can_allow_always: false } })

  it('Bash: o comando; um comando longo é cortado', () => {
    expect(reasonOf('permission', perm('Bash', 'git status'))).toBe('Pede permissão para rodar `git status`')
    const long = reasonOf('permission', perm('Bash', `echo ${'a'.repeat(300)}`))
    expect(long.length).toBeLessThanOrEqual(130)
    expect(long.endsWith('…`')).toBe(true)
  })

  it('ferramentas com arquivo, pasta ou URL: o `summary` é esse alvo', () => {
    expect(reasonOf('permission', perm('Edit', '/home/vi/dev/loja/src/a.ts'))).toBe('Pede permissão: Edit /home/vi/dev/loja/src/a.ts')
    expect(reasonOf('permission', perm('WebFetch', 'https://example.com/docs'))).toBe('Pede permissão: WebFetch https://example.com/docs')
  })

  it('sem alvo conhecido o backend manda o input em JSON: mostra só o nome da ferramenta', () => {
    expect(reasonOf('permission', perm('Grep', '{"pattern":"foo","glob":"*.ts"}'))).toBe('Pede permissão: Grep')
    expect(reasonOf('permission', perm('mcp__x__y', '{}'))).toBe('Pede permissão: mcp__x__y')
    expect(reasonOf('permission', perm('Edit', ''))).toBe('Pede permissão: Edit')
  })
})

describe('permissão do navegador', () => {
  it('sem Notification o estado é "unsupported"', () => {
    vi.stubGlobal('Notification', undefined)
    refreshNotificationPermission()
    expect(notificationPermission.value).toBe('unsupported')
  })

  it('só pede quando chamada, e guarda a resposta', async () => {
    const fake = installFakeNotification('default')
    refreshNotificationPermission()
    expect(notificationPermission.value).toBe('default')
    expect(fake.requestPermission).not.toHaveBeenCalled()
    fake.answer = 'denied'
    await requestNotificationPermission()
    expect(fake.requestPermission).toHaveBeenCalledOnce()
    expect(notificationPermission.value).toBe('denied')
  })

  it('um requestPermission que falha deixa o estado como estava', async () => {
    const fake = installFakeNotification('default')
    fake.requestPermission.mockRejectedValueOnce(new Error('x'))
    refreshNotificationPermission()
    await expect(requestNotificationPermission()).resolves.toBe('default')
  })
})

describe('notifySession', () => {
  const open = vi.fn()
  beforeEach(() => open.mockReset())

  it('mostra título da conversa, motivo e tag = session_id', () => {
    const fake = installFakeNotification('granted')
    const session = asking({ session_id: 'abc', title: 'Corrigir checkout' })
    expect(notifySession('permission', session, open)).toBe(true)
    expect(fake.instances).toHaveLength(1)
    expect(fake.instances[0]!.title).toBe('Corrigir checkout')
    expect(fake.instances[0]!.options.body).toBe('Pede permissão para rodar `pnpm test`')
    expect(fake.instances[0]!.options.tag).toBe('abc')
  })

  it('clicar foca a janela, fecha o aviso e abre a conversa', () => {
    const fake = installFakeNotification('granted')
    const focus = vi.spyOn(window, 'focus').mockImplementation(() => {})
    notifySession('question', asking({ session_id: 'abc' }), open)
    fake.instances[0]!.click()
    expect(focus).toHaveBeenCalled()
    expect(fake.instances[0]!.closed).toBe(true)
    expect(open).toHaveBeenCalledWith('abc')
    focus.mockRestore()
  })

  it('não mostra sem permissão concedida', () => {
    for (const permission of ['default', 'denied'] as const) {
      const fake = installFakeNotification(permission)
      expect(notifySession('permission', asking(), open)).toBe(false)
      expect(fake.instances).toHaveLength(0)
    }
    vi.stubGlobal('Notification', undefined)
    expect(notifySession('permission', asking(), open)).toBe(false)
  })

  it('respeita o tipo desligado', () => {
    const fake = installFakeNotification('granted')
    expect(notifySession('finished', idle(), open)).toBe(false) // desligado por padrão
    setNotificationPref('question', false)
    expect(notifySession('question', asking(), open)).toBe(false)
    setNotificationPref('finished', true)
    expect(notifySession('finished', idle(), open)).toBe(true)
    setNotificationPref('subagentFailed', false)
    expect(notifySession('subagent', idle(), open)).toBe(false)
    expect(fake.instances).toHaveLength(1)
  })

  it('"só fora de foco" bloqueia com a aba visível e libera com ela oculta', () => {
    const fake = installFakeNotification('granted')
    setHidden(false)
    expect(notifySession('permission', asking(), open)).toBe(false)
    setHidden(true)
    expect(notifySession('permission', asking(), open)).toBe(true)
    setNotificationPref('onlyWhenHidden', false)
    setHidden(false)
    expect(notifySession('permission', asking(), open)).toBe(true)
    expect(fake.instances).toHaveLength(2)
  })

  it('som só com permissão, pergunta e plano, e só se ligado', () => {
    installFakeNotification('granted')
    vi.stubGlobal('AudioContext', FakeAudioContext)
    notifySession('permission', asking(), open)
    expect(FakeAudioContext.created).toHaveLength(0) // desligado por padrão
    setNotificationPref('sound', true)
    notifySession('permission', asking(), open)
    notifySession('question', asking(), open)
    notifySession('plan', asking(), open)
    expect(FakeAudioContext.created).toHaveLength(3)
    notifySession('finished', idle(), open) // desligado, sem aviso nem som
    setNotificationPref('finished', true)
    notifySession('finished', idle(), open)
    expect(FakeAudioContext.created).toHaveLength(3)
  })

  it('um Notification que lança não derruba o app', () => {
    vi.stubGlobal('Notification', Object.assign(function Broken() { throw new Error('x') }, { permission: 'granted' }))
    expect(notifySession('permission', asking(), open)).toBe(false)
  })
})

describe('sendTestNotification', () => {
  it('mostra um aviso de teste mesmo com a aba em foco, e só com permissão', () => {
    setHidden(false)
    const fake = installFakeNotification('default')
    expect(sendTestNotification()).toBe(false)
    FakeNotification.permission = 'granted'
    expect(sendTestNotification()).toBe(true)
    expect(fake.instances[0]!.title).toBe('Cláudio Maestro')
    expect(fake.instances[0]!.options.body).toContain('funcionando')
  })
})

describe('som', () => {
  it('bip curto e baixo, sem arquivo de áudio', () => {
    vi.stubGlobal('AudioContext', FakeAudioContext)
    playAlertSound()
    const ctx = FakeAudioContext.created[0]!
    expect(ctx.oscillators[0]!.started).toBe(true)
    expect(ctx.oscillators[0]!.stopped).toBe(true)
    expect(ctx.gains[0]!.peak).toBeLessThanOrEqual(0.15)
    ctx.oscillators[0]!.onended?.()
    expect(ctx.closed).toBe(true)
  })

  it('sem WebAudio, ou com ele quebrado, não faz nada', () => {
    vi.stubGlobal('AudioContext', undefined)
    expect(() => playAlertSound()).not.toThrow()
    vi.stubGlobal('AudioContext', function Broken() { throw new Error('x') })
    expect(() => playAlertSound()).not.toThrow()
  })
})

describe('bindNotifications', () => {
  const open = vi.fn()
  let sessions: ReturnType<typeof useSessionsStore>
  let stop: () => void

  beforeEach(() => {
    setActivePinia(createPinia())
    open.mockReset()
    sessions = useSessionsStore()
  })
  afterEach(() => stop?.())

  const put = (...list: ReturnType<typeof makeSession>[]) => sessions.setForProject(1, list)

  it('não avisa sobre o que já estava lá quando as conversas foram carregadas', async () => {
    const fake = installFakeNotification('granted')
    stop = bindNotifications(sessions, open)
    put(asking({ session_id: 'a' }))
    sessions.loaded = true
    await nextTick()
    expect(fake.instances).toHaveLength(0)
  })

  it('avisa quando uma conversa entra em "precisa de você" e não repete', async () => {
    const fake = installFakeNotification('granted')
    put(running({ session_id: 'a', title: 'Loja' }))
    sessions.loaded = true
    stop = bindNotifications(sessions, open)
    await nextTick()
    sessions.applyEvent({ session_id: 'a', seq: 1, type: 'session.state', data: { state: 'awaiting_decision', error: null } })
    await nextTick()
    expect(fake.instances).toHaveLength(0) // o motivo ainda não chegou
    sessions.applyEvent({ session_id: 'a', seq: 2, type: 'session.updated', data: asking({ session_id: 'a', title: 'Loja', seq: 2 }) })
    await nextTick()
    expect(fake.instances).toHaveLength(1)
    expect(fake.instances[0]!.title).toBe('Loja')
    expect(fake.instances[0]!.options.tag).toBe('a')
    sessions.applyEvent({ session_id: 'a', seq: 3, type: 'session.updated', data: asking({ session_id: 'a', title: 'Loja', seq: 3, last_activity_at: 99 }) })
    await nextTick()
    expect(fake.instances).toHaveLength(1)
  })

  it('o clique no aviso abre a conversa', async () => {
    const fake = installFakeNotification('granted')
    vi.spyOn(window, 'focus').mockImplementation(() => {})
    put(running({ session_id: 'a' }))
    sessions.loaded = true
    stop = bindNotifications(sessions, open)
    await nextTick()
    put(asking({ session_id: 'a' }))
    await nextTick()
    fake.instances[0]!.click()
    expect(open).toHaveBeenCalledWith('a')
  })

  it('turno concluído só avisa com a opção ligada, e a aba visível barra', async () => {
    const fake = installFakeNotification('granted')
    put(running({ session_id: 'a' }))
    sessions.loaded = true
    stop = bindNotifications(sessions, open)
    await nextTick()
    put(idle({ session_id: 'a', unread: true }))
    await nextTick()
    expect(fake.instances).toHaveLength(0) // "Turno concluído" desligado

    setNotificationPref('finished', true)
    put(running({ session_id: 'a' }))
    await nextTick()
    setHidden(false)
    put(idle({ session_id: 'a', unread: true }))
    await nextTick()
    expect(fake.instances).toHaveLength(0) // aba em foco

    put(running({ session_id: 'a' }))
    await nextTick()
    setHidden(true)
    put(idle({ session_id: 'a', unread: true }))
    await nextTick()
    expect(fake.instances).toHaveLength(1)
    expect(fake.instances[0]!.options.body).toBe('Concluiu o turno')
  })

  it('conversa nova, sem anterior conhecida, não avisa; parar de observar também', async () => {
    const fake = installFakeNotification('granted')
    put(running({ session_id: 'a' }))
    sessions.loaded = true
    stop = bindNotifications(sessions, open)
    await nextTick()
    put(running({ session_id: 'a' }), asking({ session_id: 'novo' }))
    await nextTick()
    expect(fake.instances).toHaveLength(0)
    stop()
    put(asking({ session_id: 'a' }))
    await nextTick()
    expect(fake.instances).toHaveLength(0)
  })
})
