import { ref, watch } from 'vue'
import { hasRequest, isDiscarded } from './conversation/marks'
import { needsYou } from './conversation/needsYou'
import { notificationPrefs, type NotificationPrefs } from './notificationPrefs'
import type { Session } from './types/api'

/** Why the user is told: a request from Claude (permission, question, plan), the end of a turn, or a failed subagent. */
export type NotifyKind = 'permission' | 'question' | 'plan' | 'finished' | 'subagent'

/** The kinds that also play the beep: the ones that wait for an answer. */
const SOUND_KINDS: readonly NotifyKind[] = ['permission', 'question', 'plan']

const PREF_OF_KIND: Record<NotifyKind, keyof NotificationPrefs> = {
  permission: 'permission',
  question: 'question',
  plan: 'plan',
  finished: 'finished',
  subagent: 'subagentFailed',
}

const KIND_OF_PENDING: Record<string, NotifyKind> = { tool: 'permission', question: 'question', plan: 'plan' }

export type PermissionState = NotificationPermission | 'unsupported'

function readPermission(): PermissionState {
  return typeof Notification === 'undefined' ? 'unsupported' : Notification.permission
}

/** Browser permission, shared with the Preferences screen. */
export const notificationPermission = ref<PermissionState>(readPermission())

export function refreshNotificationPermission(): void {
  notificationPermission.value = readPermission()
}

/** Asks the browser for permission. Only call it from a click: the app never asks by itself. */
export async function requestNotificationPermission(): Promise<PermissionState> {
  if (typeof Notification === 'undefined') return 'unsupported'
  try {
    await Notification.requestPermission()
  } catch {
    // The permission stays as it was.
  }
  refreshNotificationPermission()
  return notificationPermission.value
}

/** What the notifier remembers of a session to tell what changed. */
export interface Snapshot {
  state: Session['state']
  /** Kind and prompt of the oldest pending decision; null until the backend says which it is. */
  pending: string | null
  hasRequest: boolean
  needsYou: boolean
  discarded: boolean
}

export function snapshotOf(session: Session): Snapshot {
  return {
    state: session.state,
    pending: session.pending_kind ? `${session.pending_kind}:${session.pending_permission?.prompt_id ?? ''}` : null,
    hasRequest: hasRequest(session),
    needsYou: needsYou(session),
    discarded: isDiscarded(session),
  }
}

/** The notification a session change deserves, or null. Without a previous snapshot nothing is known to have changed. */
export function transitionKind(prev: Snapshot | undefined, next: Snapshot): NotifyKind | null {
  // A discarded session is hidden, so it does not notify (restoring it notifies nothing old).
  if (!prev || next.discarded) return null
  if (next.pending && next.pending !== prev.pending) return KIND_OF_PENDING[next.pending.split(':', 1)[0]!] ?? null
  if (next.state === 'error' && prev.state !== 'error') return 'finished'
  if (next.needsYou && !prev.needsYou && !next.hasRequest) return 'finished'
  return null
}

const MAX_TARGET = 100

function clip(text: string): string {
  return text.length > MAX_TARGET ? `${text.slice(0, MAX_TARGET - 1)}…` : text
}

/**
 * The reason in one sentence. For a tool, the backend's `pending_permission.summary` is the command, file, path or
 * URL the tool works on (whitespace collapsed, at most 200 characters) or, when the input has none of these, the
 * input as JSON. The JSON is not worth showing in a notification, so only the tool name is kept then.
 */
export function reasonOf(kind: NotifyKind, session: Session): string {
  if (kind === 'permission') {
    const perm = session.pending_permission
    if (!perm) return 'Pede permissão'
    const target = perm.summary.trim()
    if (perm.tool_name === 'Bash' && target) return `Pede permissão para rodar \`${clip(target)}\``
    if (!target || target.startsWith('{') || target.startsWith('[')) return `Pede permissão: ${perm.tool_name}`
    return `Pede permissão: ${perm.tool_name} ${clip(target)}`
  }
  if (kind === 'question') return 'Fez uma pergunta'
  if (kind === 'plan') return 'Plano para aprovar'
  if (kind === 'subagent') return 'Um subagente falhou'
  return session.state === 'error' ? 'Parou com erro' : 'Concluiu o turno'
}

/** A short, low beep made with WebAudio (no audio file). Does nothing where WebAudio is missing or refuses. */
export function playAlertSound(): void {
  try {
    const Ctx = typeof AudioContext === 'undefined'
      ? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
      : AudioContext
    if (!Ctx) return
    const ctx = new Ctx()
    void ctx.resume?.()?.catch?.(() => {})
    const osc = ctx.createOscillator()
    const gain = ctx.createGain()
    const t = ctx.currentTime
    osc.type = 'sine'
    osc.frequency.value = 523
    gain.gain.setValueAtTime(0.0001, t)
    gain.gain.exponentialRampToValueAtTime(0.08, t + 0.02)
    gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.22)
    osc.connect(gain)
    gain.connect(ctx.destination)
    osc.onended = () => { void ctx.close?.()?.catch?.(() => {}) }
    osc.start(t)
    osc.stop(t + 0.24)
  } catch {
    // No sound is not worth failing for.
  }
}

function show(title: string, body: string, tag: string): Notification | null {
  if (readPermission() !== 'granted') return null
  try {
    // `silent`: the beep is ours and follows the "Tocar som" option.
    return new Notification(title, { body, tag, silent: true })
  } catch {
    return null
  }
}

/**
 * Shows the notification of a kind when the options and the browser allow it: permission granted, the kind
 * switched on and, with "só fora de foco", the app out of sight. Clicking it focuses the window and calls `open`.
 */
export function notifySession(kind: NotifyKind, session: Session, open: (sessionId: string) => void): boolean {
  const prefs = notificationPrefs.value
  if (!prefs[PREF_OF_KIND[kind]]) return false
  if (prefs.onlyWhenHidden && !document.hidden) return false
  const shown = show(session.title, reasonOf(kind, session), session.session_id)
  if (!shown) return false
  shown.onclick = () => {
    window.focus()
    shown.close()
    open(session.session_id)
  }
  if (prefs.sound && SOUND_KINDS.includes(kind)) playAlertSound()
  return true
}

/** The "Testar" button: shows right away, whatever the options. */
export function sendTestNotification(): boolean {
  return show('Cláudio Maestro', 'As notificações estão funcionando.', 'maestro-test') !== null
}

/**
 * Watches the sessions and notifies when one enters "needs you" or ends a turn. What was already there when the
 * list loaded is only remembered. Returns the function that stops it.
 */
export function bindNotifications(
  sessions: { loaded: boolean; all: Session[] },
  open: (sessionId: string) => void,
): () => void {
  let known: Map<string, Snapshot> | null = null
  return watch(
    () => (sessions.loaded ? sessions.all.map((s) => [s, snapshotOf(s)] as const) : null),
    (entries) => {
      if (!entries) return
      const previous = known
      known = new Map(entries.map(([s, snapshot]) => [s.session_id, snapshot]))
      if (!previous) return
      for (const [session, snapshot] of entries) {
        const kind = transitionKind(previous.get(session.session_id), snapshot)
        if (kind) notifySession(kind, session, open)
      }
    },
    { immediate: true },
  )
}
