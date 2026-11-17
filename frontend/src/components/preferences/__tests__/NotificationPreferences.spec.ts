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

const box = (w: ReturnType<typeof mountWith>, key: string) => w.find(`[data-test="notif-pref-${key}"]`)
const groups = (w: ReturnType<typeof mountWith>) => w.findAll('[data-test="notif-group"]')
const keysOf = (group: { findAll: (s: string) => Array<{ attributes: (n: string) => string | undefined }> }) =>
  group.findAll('[data-test^="notif-pref-"]').map((el) => el.attributes('data-test')!.replace('notif-pref-', ''))

describe('preferências de notificações', () => {
  it('nunca pede permissão ao abrir', () => {
    mountWith('default')
    expect(FakeNotification.requestPermission).not.toHaveBeenCalled()
  })

  it('permissão "default": aviso laranja com "Ativar notificações", que pede só no clique', async () => {
    const w = mountWith('default')
    const button = w.find('[data-test="notif-enable"]')
    expect(button.text()).toBe('Ativar notificações')
    expect(button.classes()).toEqual(expect.arrayContaining(['bg-secondary', 'h-9']))
    const notice = button.element.closest('[data-test="notif-notice"]')!
    expect(notice).not.toBeNull()
    expect(notice.textContent).toContain('Ainda não ativadas neste navegador.')
    expect(notice.textContent).toContain('o navegador vai pedir a sua confirmação')
    expect(notice.className).toContain('bg-secondary-tint')
    await button.trigger('click')
    await flushPromises()
    expect(FakeNotification.requestPermission).toHaveBeenCalledOnce()
    expect(w.find('[data-test="notif-enable"]').exists()).toBe(false)
    expect(w.find('[data-test="notif-notice"]').exists()).toBe(false)
    expect(w.find('[data-test="notif-granted"]').text()).toContain('Notificações ativas neste navegador')
  })

  it('permissão negada no pedido mostra como liberar', async () => {
    const w = mountWith('default')
    FakeNotification.answer = 'denied'
    await w.find('[data-test="notif-enable"]').trigger('click')
    await flushPromises()
    expect(w.find('[data-test="notif-denied"]').exists()).toBe(true)
  })

  it('"granted": mostra o estado, sem aviso de ativação', () => {
    const w = mountWith('granted')
    expect(w.find('[data-test="notif-granted"]').text()).toContain('Notificações ativas neste navegador')
    expect(w.find('[data-test="notif-enable"]').exists()).toBe(false)
    expect(w.find('[data-test="notif-notice"]').exists()).toBe(false)
  })

  it('"denied": explica como liberar nas configurações do site, no aviso laranja', () => {
    const w = mountWith('denied')
    const denied = w.find('[data-test="notif-denied"]')
    expect(denied.text()).toContain('bloqueadas')
    expect(denied.text()).toContain('configurações do site')
    expect(denied.classes()).toContain('bg-secondary-tint')
    expect(w.find('[data-test="notif-enable"]').exists()).toBe(false)
    expect(w.find('[data-test="notif-test"]').attributes('disabled')).toBeDefined()
  })

  it('sem suporte do navegador avisa e não oferece o botão de ativar', () => {
    vi.stubGlobal('Notification', undefined)
    const w = mount(NotificationPreferences)
    expect(w.find('[data-test="notif-unsupported"]').exists()).toBe(true)
    // Nothing for the person to do, so no orange (orange is for what waits on them).
    expect(w.find('[data-test="notif-unsupported"]').classes()).not.toContain('bg-secondary-tint')
    expect(w.find('[data-test="notif-unsupported"]').html()).not.toContain('secondary')
    expect(w.find('[data-test="notif-enable"]').exists()).toBe(false)
    expect(w.find('[data-test="notif-test"]').attributes('disabled')).toBeDefined()
    expect(w.text()).not.toContain('O teste fica disponível depois de ativar.')
    expect(w.text()).toContain('Estas escolhas valem só neste navegador.')
  })

  it('três grupos: precisa de você, para acompanhar e como', () => {
    const w = mountWith('granted')
    const all = groups(w)
    expect(all.map((g) => g.attributes('data-group'))).toEqual(['needs-you', 'follow', 'how'])
    expect(keysOf(all[0]!)).toEqual(['permission', 'question', 'plan'])
    expect(keysOf(all[1]!)).toEqual(['finished', 'specialistNotice'])
    expect(keysOf(all[2]!)).toEqual(['onlyWhenHidden', 'sound'])
    expect(all[0]!.text()).toContain('Precisa de você')
    expect(all[1]!.text()).toContain('Para acompanhar')
    expect(all[2]!.text()).toContain('Como')
    // "Subagente falhou" fica fora da tela enquanto a lista de sessões não traz essa informação.
    expect(box(w, 'subagentFailed').exists()).toBe(false)
    expect(w.text()).not.toContain('Subagente')
  })

  it('cada opção é uma chave com rótulo e explicação, nos valores do plano', () => {
    const w = mountWith('granted')
    const expected: Record<string, boolean> = {
      permission: true, question: true, plan: true, finished: false, specialistNotice: true, onlyWhenHidden: true, sound: false,
    }
    for (const [key, on] of Object.entries(expected)) {
      const sw = box(w, key)
      expect(sw.attributes('role')).toBe('switch')
      expect(sw.attributes('aria-checked')).toBe(String(on))
      expect(sw.attributes('aria-label')).toBeTruthy()
    }
    expect(w.text()).toContain('Pedido de permissão')
    expect(w.text()).toContain('O Claude quer rodar um comando ou editar um arquivo.')
    expect(w.text()).toContain('Avisos dos agentes')
    expect(w.text()).toContain('Só quando o Maestro não estiver em foco')
    expect(w.text()).toContain('Bipe curto e baixo, só para permissão, pergunta e plano.')
  })

  it('ligar e desligar muda a preferência e salva neste navegador', async () => {
    const w = mountWith('granted')
    await box(w, 'finished').trigger('click')
    await box(w, 'question').trigger('click')
    expect(notificationPrefs.value.finished).toBe(true)
    expect(notificationPrefs.value.question).toBe(false)
    expect(box(w, 'finished').attributes('aria-checked')).toBe('true')
    expect(JSON.parse(localStorage.getItem('maestro:notifications')!)).toMatchObject({ finished: true, question: false })
  })

  it('a chave aceita o teclado (Espaço)', async () => {
    const w = mountWith('granted')
    await box(w, 'sound').trigger('keydown', { key: ' ' })
    await box(w, 'sound').trigger('keyup', { key: ' ' })
    expect(notificationPrefs.value.sound).toBe(true)
  })

  it('as opções ficam ativas mesmo antes de a permissão ser dada', () => {
    const w = mountWith('default')
    expect(box(w, 'sound').attributes('disabled')).toBeUndefined()
  })

  it('"Enviar um teste" existe em qualquer estado e só vale com a permissão concedida', async () => {
    for (const permission of ['default', 'denied'] as const) {
      const w = mountWith(permission)
      const test = w.find('[data-test="notif-test"]')
      expect(test.text()).toBe('Enviar um teste')
      expect(test.attributes('disabled')).toBeDefined()
      await test.trigger('click')
      expect(FakeNotification.instances).toHaveLength(0)
      expect(w.text()).toContain('O teste fica disponível depois de ativar.')
    }
    const w = mountWith('granted')
    const test = w.find('[data-test="notif-test"]')
    expect(test.attributes('disabled')).toBeUndefined()
    expect(w.text()).not.toContain('O teste fica disponível depois de ativar.')
    await test.trigger('click')
    expect(FakeNotification.instances).toHaveLength(1)
  })

  it('"Ouvir" toca o bipe, com ou sem permissão, sem mudar a opção do som', async () => {
    const created: unknown[] = []
    class FakeAudio {
      currentTime = 0
      destination = {}
      constructor() { created.push(this) }
      resume() { return Promise.resolve() }
      close() { return Promise.resolve() }
      createOscillator() { return { type: '', frequency: { value: 0 }, connect() {}, start() {}, stop() {}, onended: null } }
      createGain() { return { gain: { setValueAtTime() {}, exponentialRampToValueAtTime() {} }, connect() {} } }
    }
    vi.stubGlobal('AudioContext', FakeAudio)
    const w = mountWith('default')
    const listen = w.find('[data-test="notif-sound-test"]')
    expect(listen.text()).toBe('Ouvir')
    expect(listen.attributes('disabled')).toBeUndefined()
    await listen.trigger('click')
    expect(created).toHaveLength(1)
    expect(notificationPrefs.value.sound).toBe(false)
  })

  it('a prévia mostra como o aviso aparece, sem disparar nada', () => {
    const w = mountWith('granted')
    const preview = w.find('[data-test="notif-preview"]')
    expect(preview.exists()).toBe(true)
    expect(preview.text()).toContain('Cláudio Maestro')
    expect(preview.text()).toContain('Ajustar a busca de projetos')
    expect(preview.text()).toContain('Pede permissão para rodar um comando.')
    expect(w.text()).toContain('O título é o da conversa e o texto diz o motivo. Clicar abre a conversa.')
    expect(FakeNotification.instances).toHaveLength(0)
  })
})
