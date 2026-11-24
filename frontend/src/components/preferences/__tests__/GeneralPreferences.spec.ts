import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import GeneralPreferences from '../GeneralPreferences.vue'
import { jsonResponse, routeFetch } from '../../../test/factories'
import { useUpdatesStore } from '../../../stores/updates'

enableAutoUnmount(afterEach)

let pinia: Pinia
let puts: Record<string, unknown>[]

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  puts = []
})
afterEach(() => vi.unstubAllGlobals())

function stub(state: Record<string, unknown>) {
  vi.stubGlobal('fetch', routeFetch({
    'GET /api/state': () => jsonResponse(state),
    'PUT /api/state/preferences': (init) => {
      const body = JSON.parse(String(init?.body)) as Record<string, unknown>
      puts.push(body)
      return jsonResponse(body)
    },
  }))
}

async function mountTab() {
  const w = mount(GeneralPreferences, { global: { plugins: [pinia] }, attachTo: document.body })
  await flushPromises()
  return w
}

describe('versão nas Preferências', () => {
  const RELEASES = 'https://github.com/vateiixeira/claudio-maestro/releases'
  const NOW = new Date(2026, 9, 5, 15, 0)
  const base = { enabled: true, current: '0.1.0', available: false, latest: null, checked_at: NOW.getTime() / 1000 - 7200, releases_url: RELEASES }
  beforeEach(() => { vi.useFakeTimers({ toFake: ['Date'] }); vi.setSystemTime(NOW); stub({ preferences: {} }) })
  afterEach(() => vi.useRealTimers())

  it('mostra a versão e quando foi verificado', async () => {
    const wrapper = await mountTab()
    useUpdatesStore().apply(base)
    await nextTick()
    expect(wrapper.get('[data-test="pref-version"]').text()).toBe('0.1.0 · verificado há 2 h')
  })

  it('mostra a versão nova e abre o modal', async () => {
    const wrapper = await mountTab()
    const updates = useUpdatesStore()
    updates.apply({ ...base, available: true, latest: { version: '0.2.0', url: `${RELEASES}/tag/v0.2.0`, notes: '', published_at: null } })
    await nextTick()
    const button = wrapper.get('[data-test="pref-version"] button')
    expect(button.text()).toBe('0.2.0 disponível')
    await button.trigger('click')
    expect(updates.modalOpen).toBe(true)
  })

  it('avisa quando a verificação está desligada', async () => {
    const wrapper = await mountTab()
    useUpdatesStore().apply({ ...base, enabled: false, checked_at: null })
    await nextTick()
    expect(wrapper.get('[data-test="pref-version"]').text()).toBe('0.1.0 · verificação de versões desligada (MAESTRO_UPDATE_CHECK=0)')
  })

  it('ainda não verificado', async () => {
    const wrapper = await mountTab()
    useUpdatesStore().apply({ ...base, checked_at: null })
    await nextTick()
    expect(wrapper.get('[data-test="pref-version"]').text()).toBe('0.1.0 · ainda não verificado')
  })
})

describe('preferências gerais: salvamento do formulário', () => {
  it('salva só o comando do editor e os dias, preservando as outras chaves', async () => {
    stub({ preferences: { editor_command: ['code'], finished_after_days: 3, tema: 'escuro' } })
    const w = await mountTab()
    await w.find('#pref-editor').setValue('"/opt/meu editor/bin" --wait')
    await w.find('#pref-days').setValue('10')
    await w.find('form').trigger('submit')
    await flushPromises()
    expect(puts).toEqual([{ editor_command: ['/opt/meu editor/bin', '--wait'], finished_after_days: 10, tema: 'escuro' }])
    expect(w.find('[data-test="saved"]').text()).toContain('Preferências salvas')
    expect(w.find('[role="alert"]').exists()).toBe(false)
  })
})
