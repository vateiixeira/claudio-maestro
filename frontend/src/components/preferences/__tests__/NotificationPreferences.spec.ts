import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import NotificationPreferences from '../NotificationPreferences.vue'
import { FakeNotification, installFakeNotification, type FakePermission } from '../../../test/fakeNotification'
import { DEFAULT_NOTIFICATION_PREFS, notificationPrefs } from '../../../notificationPrefs'

enableAutoUnmount(afterEach)

beforeEach(() => {
  localStorage.clear()
  notificationPrefs.value = { ...DEFAULT_NOTIFICATION_PREFS }
})
afterEach(() => vi.unstubAllGlobals())

function mountWith(permission: FakePermission) {
  installFakeNotification(permission)
  return mount(NotificationPreferences)
}

const box = (w: ReturnType<typeof mountWith>, key: string) => w.find<HTMLInputElement>(`[data-test="notif-pref-${key}"]`)

describe('preferências de notificações', () => {
  it('nunca pede permissão ao abrir', () => {
    mountWith('default')
    expect(FakeNotification.requestPermission).not.toHaveBeenCalled()
  })

  it('permissão "default": explica e oferece "Ativar notificações", que pede só no clique', async () => {
    const w = mountWith('default')
    const button = w.find('[data-test="notif-enable"]')
    expect(button.text()).toBe('Ativar notificações')
    expect(button.classes()).toEqual(expect.arrayContaining(['bg-primary', 'h-9']))
    expect(w.find('[data-test="notif-test"]').exists()).toBe(false)
    await button.trigger('click')
    await flushPromises()
    expect(FakeNotification.requestPermission).toHaveBeenCalledOnce()
    expect(w.find('[data-test="notif-enable"]').exists()).toBe(false)
    expect(w.find('[data-test="notif-granted"]').text()).toContain('Notificações ativas neste navegador')
  })

  it('permissão negada no pedido mostra como liberar', async () => {
    const w = mountWith('default')
    FakeNotification.answer = 'denied'
    await w.find('[data-test="notif-enable"]').trigger('click')
    await flushPromises()
    expect(w.find('[data-test="notif-denied"]').exists()).toBe(true)
  })

  it('"granted": mostra o estado e "Testar" dispara um aviso', async () => {
    const w = mountWith('granted')
    expect(w.find('[data-test="notif-granted"]').text()).toContain('Notificações ativas neste navegador')
    expect(w.find('[data-test="notif-enable"]').exists()).toBe(false)
    await w.find('[data-test="notif-test"]').trigger('click')
    expect(FakeNotification.instances).toHaveLength(1)
  })

  it('"denied": explica como liberar nas configurações do site', () => {
    const w = mountWith('denied')
    const denied = w.find('[data-test="notif-denied"]')
    expect(denied.text()).toContain('bloqueadas')
    expect(denied.text()).toContain('configurações do site')
    expect(w.find('[data-test="notif-enable"]').exists()).toBe(false)
    expect(w.find('[data-test="notif-test"]').exists()).toBe(false)
  })

  it('sem suporte do navegador avisa e não oferece o botão', () => {
    vi.stubGlobal('Notification', undefined)
    const w = mount(NotificationPreferences)
    expect(w.find('[data-test="notif-unsupported"]').exists()).toBe(true)
    expect(w.find('[data-test="notif-enable"]').exists()).toBe(false)
  })

  it('as opções começam como no plano', () => {
    const w = mountWith('granted')
    expect(box(w, 'permission').element.checked).toBe(true)
    expect(box(w, 'question').element.checked).toBe(true)
    expect(box(w, 'plan').element.checked).toBe(true)
    expect(box(w, 'finished').element.checked).toBe(false)
    // "Subagente falhou" fica fora da tela enquanto a lista de sessões não traz essa informação.
    expect(box(w, 'subagentFailed').exists()).toBe(false)
    expect(w.text()).not.toContain('Subagente')
    expect(box(w, 'onlyWhenHidden').element.checked).toBe(true)
    expect(box(w, 'sound').element.checked).toBe(false)
    expect(w.text()).toContain('Só quando o Maestro não estiver em foco')
    expect(box(w, 'sound').classes()).toContain('accent-primary')
  })

  it('marcar e desmarcar muda a preferência e salva neste navegador', async () => {
    const w = mountWith('granted')
    await box(w, 'finished').setValue(true)
    await box(w, 'question').setValue(false)
    expect(notificationPrefs.value.finished).toBe(true)
    expect(notificationPrefs.value.question).toBe(false)
    expect(JSON.parse(localStorage.getItem('maestro:notifications')!)).toMatchObject({ finished: true, question: false })
  })

  it('as opções ficam ativas mesmo antes de a permissão ser dada', () => {
    const w = mountWith('default')
    expect(box(w, 'sound').attributes('disabled')).toBeUndefined()
  })
})
