import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, mount } from '@vue/test-utils'
import ThemePicker from '../ThemePicker.vue'
import { setTheme, theme } from '../../../theme'

enableAutoUnmount(afterEach)

beforeEach(() => {
  localStorage.clear()
  setTheme('maestro')
  localStorage.clear()
})
afterEach(() => {
  vi.restoreAllMocks()
  document.documentElement.removeAttribute('data-theme')
})

const options = (w: ReturnType<typeof mountPicker>) => w.findAll('[data-test="theme-option"]')
const mountPicker = () => mount(ThemePicker, { attachTo: document.body })
const radio = (w: ReturnType<typeof mountPicker>, label: string) => {
  const option = options(w).find((o) => o.text() === label)
  expect(option, `tema ${label}`).toBeDefined()
  return option!.find('input[type="radio"]')
}

describe('seletor de tema', () => {
  it('é um grupo com a legenda "Tema" e oito opções, com o Maestro marcado', () => {
    const w = mountPicker()
    expect(w.find('legend').text()).toBe('Tema')
    expect(options(w).map((o) => o.text())).toEqual([
      'Maestro',
      'Dracula',
      'Monokai Pro',
      'Monokai Machine',
      'Monokai Octagon',
      'Monokai Ristretto',
      'Monokai Spectrum',
      'Monokai Classic',
    ])
    const checked = w.findAll('input[name="theme"]').filter((i) => (i.element as HTMLInputElement).checked)
    expect(checked).toHaveLength(1)
    expect(radio(w, 'Maestro').element).toBe(checked[0].element)
  })

  it('cada opção mostra quatro amostras de cor, escondidas dos leitores de tela', () => {
    const w = mountPicker()
    for (const option of options(w)) {
      const swatches = option.findAll('[data-test="theme-swatch"]')
      expect(swatches, option.text()).toHaveLength(4)
      expect(option.find('[aria-hidden="true"]').exists(), option.text()).toBe(true)
    }
  })

  it('escolher um tema aplica na hora, atualiza o ref e salva', async () => {
    const w = mountPicker()
    await radio(w, 'Dracula').setValue(true)
    expect(theme.value).toBe('dracula')
    expect(document.documentElement.getAttribute('data-theme')).toBe('dracula')
    expect(localStorage.getItem('maestro:theme')).toBe('dracula')
    expect((radio(w, 'Dracula').element as HTMLInputElement).checked).toBe(true)
  })

  it('voltar ao Maestro tira o data-theme', async () => {
    const w = mountPicker()
    await radio(w, 'Monokai Pro').setValue(true)
    await radio(w, 'Maestro').setValue(true)
    expect(theme.value).toBe('maestro')
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false)
  })

  it('mostra o tema que já estava ativo', () => {
    setTheme('monokai-classic')
    const w = mountPicker()
    expect((radio(w, 'Monokai Classic').element as HTMLInputElement).checked).toBe(true)
    expect((radio(w, 'Maestro').element as HTMLInputElement).checked).toBe(false)
  })

  it('funciona quando o storage lança exceção ao salvar', async () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('cheio')
    })
    const w = mountPicker()
    await radio(w, 'Monokai Octagon').setValue(true)
    expect(document.documentElement.getAttribute('data-theme')).toBe('monokai-octagon')
  })
})
