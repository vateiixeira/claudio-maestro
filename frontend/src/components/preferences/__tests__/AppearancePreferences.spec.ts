import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import AppearancePreferences from '../AppearancePreferences.vue'
import { setUiScale, uiScale } from '../../../uiScale'

enableAutoUnmount(afterEach)

let pinia: Pinia

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  setUiScale(100)
  localStorage.clear()
  document.documentElement.style.fontSize = ''
})
afterEach(() => vi.unstubAllGlobals())

async function mountTab() {
  const w = mount(AppearancePreferences, { global: { plugins: [pinia] }, attachTo: document.body })
  await flushPromises()
  return w
}
type Tab = Awaited<ReturnType<typeof mountTab>>

describe('preferências de aparência: tamanho do texto', () => {
  const options = (w: Tab) => w.findAll('[data-test="ui-scale-option"]')
  const radio = (w: Tab, label: string) => {
    const opt = options(w).find((o) => o.text() === label)
    expect(opt, `opção ${label}`).toBeDefined()
    return opt!.find('input[type="radio"]')
  }

  it('mostra as seis opções, com 100% marcado por padrão', async () => {
    const w = await mountTab()
    expect(options(w).map((o) => o.text())).toEqual(['90%', '100%', '112%', '125%', '137%', '150%'])
    expect(w.findAll('input[type="radio"][name="ui-scale"]')).toHaveLength(6)
    const checked = w.findAll('input[name="ui-scale"]').filter((i) => (i.element as HTMLInputElement).checked)
    expect(checked).toHaveLength(1)
    expect((radio(w, '100%').element as HTMLInputElement).checked).toBe(true)
  })

  it('marca o tamanho atual', async () => {
    setUiScale(137.5)
    const w = await mountTab()
    expect((radio(w, '137%').element as HTMLInputElement).checked).toBe(true)
    expect((radio(w, '100%').element as HTMLInputElement).checked).toBe(false)
  })

  it('escolher 125% aplica e guarda na hora, sem chamar a API de salvar', async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    const w = await mountTab()
    await radio(w, '125%').setValue(true)
    expect(uiScale.value).toBe(125)
    expect(document.documentElement.style.fontSize).toBe('125%')
    expect(localStorage.getItem('maestro:ui-scale')).toBe('125')
    expect((radio(w, '125%').element as HTMLInputElement).checked).toBe(true)
  })

  it('funciona sem nenhum servidor de preferências', async () => {
    const w = await mountTab()
    const input = radio(w, '150%')
    expect(input.attributes('disabled')).toBeUndefined()
    await input.setValue(true)
    expect(document.documentElement.style.fontSize).toBe('150%')
    expect(localStorage.getItem('maestro:ui-scale')).toBe('150')
  })
})
