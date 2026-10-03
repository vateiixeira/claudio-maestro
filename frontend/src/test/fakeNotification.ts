import { vi } from 'vitest'

export type FakePermission = 'default' | 'granted' | 'denied'

/** Stand-in for the browser's `Notification`; every notification shown is kept in `instances`. */
export class FakeNotification {
  static permission: FakePermission = 'default'
  static instances: FakeNotification[] = []
  /** What `requestPermission()` answers; it also becomes the new `permission`. */
  static answer: FakePermission = 'granted'
  static requestPermission = vi.fn(async () => {
    FakeNotification.permission = FakeNotification.answer
    return FakeNotification.permission
  })

  onclick: ((event: unknown) => void) | null = null
  closed = false
  title: string
  options: NotificationOptions
  constructor(title: string, options: NotificationOptions = {}) {
    this.title = title
    this.options = options
    FakeNotification.instances.push(this)
  }
  close() { this.closed = true }
  click() { this.onclick?.({}) }

  static reset(permission: FakePermission = 'default') {
    FakeNotification.permission = permission
    FakeNotification.answer = 'granted'
    FakeNotification.instances = []
    FakeNotification.requestPermission.mockClear()
  }
}

/** Installs the fake as the global `Notification`; undo with `vi.unstubAllGlobals()`. */
export function installFakeNotification(permission: FakePermission = 'default') {
  FakeNotification.reset(permission)
  vi.stubGlobal('Notification', FakeNotification)
  return FakeNotification
}

/** Stand-in for WebAudio: counts the beeps and exposes what was set on the nodes. */
export class FakeAudioContext {
  static created: FakeAudioContext[] = []
  currentTime = 0
  state = 'running'
  destination = {}
  oscillators: Array<{ type: string; frequency: { value: number }; started: boolean; stopped: boolean; onended: null | (() => void) }> = []
  gains: Array<{ peak: number }> = []
  closed = false
  constructor() { FakeAudioContext.created.push(this) }
  createOscillator() {
    const osc = {
      type: 'sine', frequency: { value: 0 }, started: false, stopped: false,
      onended: null as null | (() => void),
      connect: vi.fn(), start() { osc.started = true }, stop() { osc.stopped = true },
    }
    this.oscillators.push(osc)
    return osc
  }
  createGain() {
    const entry = { peak: 0 }
    this.gains.push(entry)
    return {
      connect: vi.fn(),
      gain: {
        value: 0,
        setValueAtTime: vi.fn(),
        exponentialRampToValueAtTime: vi.fn((v: number) => { entry.peak = Math.max(entry.peak, v) }),
      },
    }
  }
  async resume() { this.state = 'running' }
  async close() { this.closed = true }
}
