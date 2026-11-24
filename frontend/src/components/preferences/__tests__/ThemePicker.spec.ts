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

const mountPicker = () => mount(ThemePicker, { attachTo: document.body })
type Picker = ReturnType<typeof mountPicker>
const options = (w: Picker) => w.findAll('[data-test="theme-option"]')
const option = (w: Picker, label: string) => {
  const found = options(w).find((o) => o.find('[data-test="theme-name"]').text() === label)
  expect(found, `tema ${label}`).toBeDefined()
  return found!
}
const radio = (w: Picker, label: string) => option(w, label).find('input[type="radio"]')
const preview = (w: Picker) => w.find('[data-test="theme-preview"]')

describe('seletor de tema', () => {
  it('é um grupo com a legenda "Tema" e oito opções, com o Maestro marcado', () => {
    const w = mountPicker()
    expect(w.find('legend').text()).toBe('Tema')
    expect(options(w).map((o) => o.find('[data-test="theme-name"]').text())).toEqual([
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

  it('cada cartão é pintado com o próprio tema (data-theme igual ao id)', () => {
    const w = mountPicker()
    expect(options(w).map((o) => o.attributes('data-theme'))).toEqual([
      'maestro',
      'dracula',
      'monokai-pro',
      'monokai-machine',
      'monokai-octagon',
      'monokai-ristretto',
      'monokai-spectrum',
      'monokai-classic',
    ])
  })

  it('só o cartão ativo mostra a marca "Ativo"', async () => {
    const w = mountPicker()
    expect(w.findAll('[data-test="theme-active"]')).toHaveLength(1)
    expect(option(w, 'Maestro').find('[data-test="theme-active"]').text()).toBe('Ativo')
    await radio(w, 'Dracula').setValue(true)
    expect(w.findAll('[data-test="theme-active"]')).toHaveLength(1)
    expect(option(w, 'Dracula').find('[data-test="theme-active"]').exists()).toBe(true)
  })

  it('escolher um tema aplica na hora, atualiza o ref e salva', async () => {
    const w = mountPicker()
    await radio(w, 'Dracula').setValue(true)
    expect(theme.value).toBe('dracula')
    expect(document.documentElement.getAttribute('data-theme')).toBe('dracula')
    expect(localStorage.getItem('maestro:theme')).toBe('dracula')
    expect((radio(w, 'Dracula').element as HTMLInputElement).checked).toBe(true)
  })

  it('voltar ao Maestro tira o data-theme do html', async () => {
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

describe('amostras de cor de cada tema', () => {
  const TOKENS = ['bg', 'elevated', 'primary', 'secondary', 'info', 'diff-del-fg']

  it('cada cartão tem seis amostras, nesta ordem de tokens', () => {
    const w = mountPicker()
    for (const o of options(w)) {
      expect(o.findAll('[data-test="theme-swatch"]').map((s) => s.attributes('data-token'))).toEqual(TOKENS)
    }
  })

  it('cada amostra usa a cor do token, resolvida pelo data-theme do cartão', () => {
    const w = mountPicker()
    for (const o of options(w)) {
      for (const s of o.findAll('[data-test="theme-swatch"]')) {
        expect(s.attributes('style')).toContain(`var(--color-${s.attributes('data-token')})`)
      }
    }
  })

  it('as amostras são decorativas, escondidas dos leitores de tela', () => {
    const w = mountPicker()
    const row = option(w, 'Dracula').find('[data-test="theme-swatch"]').element.parentElement!
    expect(row.getAttribute('aria-hidden')).toBe('true')
  })

  it('não mostra mais a linha de código de exemplo', () => {
    const w = mountPicker()
    for (const o of options(w)) expect(o.text()).not.toContain("const theme = 'ok'")
    expect(w.text()).not.toContain("'ok'")
  })

  it('a grade escolhe as colunas pela largura do painel, não da janela', () => {
    // Ao lado da lista de abas o painel é estreito mesmo em janela larga.
    const w = mountPicker()
    const grid = options(w)[0].element.parentElement!
    expect(grid.parentElement!.className).toContain('@container')
    expect(grid.className).toContain('@3xl:grid-cols-4')
    expect(grid.className).not.toContain('lg:grid-cols-4')
  })
})

describe('prévia da sessão no seletor', () => {
  it('começa mostrando o tema ativo, com a legenda', () => {
    const w = mountPicker()
    expect(preview(w).attributes('data-theme')).toBe('maestro')
    expect(w.find('[data-test="theme-preview-caption"]').text()).toBe('Prévia: Maestro')
  })

  it('segue o cartão sob o mouse, sem trocar o tema do app, e volta ao ativo ao sair', async () => {
    const w = mountPicker()
    await option(w, 'Dracula').trigger('mouseenter')
    expect(preview(w).attributes('data-theme')).toBe('dracula')
    expect(w.find('[data-test="theme-preview-caption"]').text()).toBe('Prévia: Dracula')
    expect(theme.value).toBe('maestro')
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false)
    await option(w, 'Dracula').trigger('mouseleave')
    expect(preview(w).attributes('data-theme')).toBe('maestro')
  })

  it('segue o cartão com foco do teclado, e o mouse tem prioridade sobre o foco', async () => {
    const w = mountPicker()
    await option(w, 'Monokai Pro').trigger('focusin')
    expect(preview(w).attributes('data-theme')).toBe('monokai-pro')
    await option(w, 'Dracula').trigger('mouseenter')
    expect(preview(w).attributes('data-theme')).toBe('dracula')
    await option(w, 'Dracula').trigger('mouseleave')
    expect(preview(w).attributes('data-theme')).toBe('monokai-pro')
    await option(w, 'Monokai Pro').trigger('focusout')
    expect(preview(w).attributes('data-theme')).toBe('maestro')
  })

  it('depois de escolher, a prévia mostra o novo tema ativo', async () => {
    const w = mountPicker()
    await radio(w, 'Monokai Spectrum').setValue(true)
    expect(preview(w).attributes('data-theme')).toBe('monokai-spectrum')
  })
})
