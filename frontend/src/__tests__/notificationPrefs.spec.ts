import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

beforeEach(() => { localStorage.clear(); vi.resetModules() })
afterEach(() => vi.restoreAllMocks())

const DEFAULTS = {
  permission: true,
  question: true,
  plan: true,
  finished: false,
  subagentFailed: true,
  onlyWhenHidden: true,
  sound: false,
}

describe('preferências de notificação deste navegador', () => {
  it('sem nada salvo usa os padrões do plano', async () => {
    const mod = await import('../notificationPrefs')
    expect(mod.DEFAULT_NOTIFICATION_PREFS).toEqual(DEFAULTS)
    expect(mod.readNotificationPrefs()).toEqual(DEFAULTS)
    expect(mod.notificationPrefs.value).toEqual(DEFAULTS)
  })

  it('relê o que foi salvo e completa o que faltar com o padrão', async () => {
    localStorage.setItem('maestro:notifications', JSON.stringify({ finished: true, sound: true, plan: false }))
    const mod = await import('../notificationPrefs')
    expect(mod.readNotificationPrefs()).toEqual({ ...DEFAULTS, finished: true, sound: true, plan: false })
  })

  it('ignora valores que não são booleanos e JSON quebrado', async () => {
    const mod = await import('../notificationPrefs')
    localStorage.setItem('maestro:notifications', JSON.stringify({ finished: 'sim', sound: 1, question: false }))
    expect(mod.readNotificationPrefs()).toEqual({ ...DEFAULTS, question: false })
    localStorage.setItem('maestro:notifications', '{nao json')
    expect(mod.readNotificationPrefs()).toEqual(DEFAULTS)
    localStorage.setItem('maestro:notifications', '[1,2]')
    expect(mod.readNotificationPrefs()).toEqual(DEFAULTS)
  })

  it('setNotificationPref atualiza o ref e salva só esta opção em cima das outras', async () => {
    const mod = await import('../notificationPrefs')
    mod.setNotificationPref('sound', true)
    expect(mod.notificationPrefs.value.sound).toBe(true)
    expect(mod.notificationPrefs.value.question).toBe(true)
    expect(JSON.parse(localStorage.getItem('maestro:notifications')!)).toEqual({ ...DEFAULTS, sound: true })
  })

  it('funciona com o localStorage quebrado', async () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('x') })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('x') })
    const mod = await import('../notificationPrefs')
    expect(mod.readNotificationPrefs()).toEqual(DEFAULTS)
    expect(() => mod.setNotificationPref('finished', true)).not.toThrow()
    expect(mod.notificationPrefs.value.finished).toBe(true)
  })
})
