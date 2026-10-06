import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { DOMWrapper, enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import GeneralPreferences from '../GeneralPreferences.vue'
import { jsonResponse, routeFetch } from '../../../test/factories'
import { setUiScale, uiScale } from '../../../uiScale'
import { useUpdatesStore } from '../../../stores/updates'

enableAutoUnmount(afterEach)

const MODELS = [
  { value: 'opus', displayName: 'Opus', description: 'O mais capaz' },
  { value: 'sonnet', displayName: 'Sonnet', description: 'Equilibrado' },
]

let pinia: Pinia
let puts: Record<string, unknown>[]

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  puts = []
  setUiScale(100)
  localStorage.clear()
  document.documentElement.style.fontSize = ''
})
afterEach(() => vi.unstubAllGlobals())

function stub(preferences: Record<string, unknown>) {
  vi.stubGlobal('fetch', routeFetch({
    'GET /api/state': () => jsonResponse({ preferences }),
    'GET /api/models': () => jsonResponse(MODELS),
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
type Tab = Awaited<ReturnType<typeof mountTab>>

const trigger = (w: Tab, name: string) => w.find(`[data-test="${name}"] button`)
async function choose(w: Tab, name: string, label: string) {
  await trigger(w, name).trigger('click')
  await flushPromises()
  const items = new DOMWrapper(document.body).findAll('[role="menuitemradio"]')
  const item = items.find((i) => i.text().startsWith(label))
  expect(item, `opção ${label}`).toBeDefined()
  await item!.trigger('click')
  await flushPromises()
}
async function menuLabels(w: Tab, name: string) {
  await trigger(w, name).trigger('click')
  await flushPromises()
  const labels = new DOMWrapper(document.body).findAll('[role="menuitemradio"] > span:first-child').map((i) => i.text())
  await new DOMWrapper(document.body).find('[role="menu"]').trigger('keydown', { key: 'Escape' })
  await flushPromises()
  return labels
}

describe('preferências gerais: padrões das conversas novas', () => {
  it('mostra o que veio salvo e "Padrão" quando não há valor', async () => {
    stub({ new_session_model: 'opus', new_session_effort: 'high' })
    const w = await mountTab()
    expect(trigger(w, 'pref-new-model').text()).toBe('Opus')
    expect(trigger(w, 'pref-new-effort').text()).toBe('Raciocínio alto')
    expect(trigger(w, 'pref-new-mode').text()).toBe('Modo padrão')
  })

  it('o modo oferece "Sem perguntas" e a lista de modelos vem do catálogo', async () => {
    stub({})
    const w = await mountTab()
    const modes = await menuLabels(w, 'pref-new-mode')
    expect(modes[0]).toBe('Padrão da conta')
    expect(modes).toContain('Sem perguntas')
    expect(modes).toContain('Aceita edições')
    expect(await menuLabels(w, 'pref-new-model')).toEqual(['Padrão', 'Opus', 'Sonnet'])
  })

  it('salva as três chaves junto das que já existem', async () => {
    stub({ editor_command: ['code'], finished_after_days: 7 })
    const w = await mountTab()
    await choose(w, 'pref-new-model', 'Sonnet')
    await choose(w, 'pref-new-effort', 'médio')
    await choose(w, 'pref-new-mode', 'Aceita edições')
    await w.find('form').trigger('submit')
    await flushPromises()
    expect(puts).toEqual([{
      editor_command: ['code'], finished_after_days: 7,
      new_session_model: 'sonnet', new_session_effort: 'medium', new_session_mode: 'acceptEdits',
    }])
  })

  it('"Padrão" salva null', async () => {
    stub({ new_session_model: 'opus', new_session_effort: 'high', new_session_mode: 'plan' })
    const w = await mountTab()
    await choose(w, 'pref-new-model', 'Padrão')
    await choose(w, 'pref-new-effort', 'Padrão')
    await choose(w, 'pref-new-mode', 'Padrão da conta')
    await w.find('form').trigger('submit')
    await flushPromises()
    expect(puts).toHaveLength(1)
    expect(puts[0]).toMatchObject({ new_session_model: null, new_session_effort: null, new_session_mode: null })
  })

  it('"Pede permissão" salva "default", diferente de "Padrão da conta"', async () => {
    stub({})
    const w = await mountTab()
    await choose(w, 'pref-new-mode', 'Pede permissão')
    await w.find('form').trigger('submit')
    await flushPromises()
    expect(puts).toHaveLength(1)
    expect(puts[0]).toMatchObject({ new_session_mode: 'default' })
    expect(trigger(w, 'pref-new-mode').text()).toBe('Pede permissão')
  })

  it('com "default" salvo só "Pede permissão" fica marcado; sem valor, só "Padrão da conta"', async () => {
    const checked = async (w: Tab) => {
      await trigger(w, 'pref-new-mode').trigger('click')
      await flushPromises()
      const items = new DOMWrapper(document.body).findAll('[role="menuitemradio"]')
      const marked = items.filter((i) => i.attributes('aria-checked') === 'true').map((i) => i.text())
      await new DOMWrapper(document.body).find('[role="menu"]').trigger('keydown', { key: 'Escape' })
      await flushPromises()
      return marked
    }
    stub({ new_session_mode: 'default' })
    const saved = await mountTab()
    expect(await checked(saved)).toEqual(['Pede permissão'])
    saved.unmount()
    stub({})
    const empty = await mountTab()
    expect(await checked(empty)).toEqual(['Padrão da conta'])
  })

  it('as opções de cada menu têm valores distintos, mesmo com "default" vindo do SDK', async () => {
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/state': () => jsonResponse({ preferences: {} }),
      'GET /api/models': () => jsonResponse([{ value: 'default', displayName: 'Padrão do SDK', description: '' }, ...MODELS]),
    }))
    const w = await mountTab()
    await trigger(w, 'pref-new-model').trigger('click')
    await flushPromises()
    const marked = new DOMWrapper(document.body).findAll('[role="menuitemradio"]')
      .filter((i) => i.attributes('aria-checked') === 'true')
    expect(marked).toHaveLength(1)
    expect(marked[0].text().startsWith('Padrão')).toBe(true)
  })

  it('ignora valores salvos de tipo errado', async () => {
    stub({ new_session_model: 5, new_session_effort: 'turbo', new_session_mode: 'inventado' })
    const w = await mountTab()
    expect(trigger(w, 'pref-new-model').text()).toBe('Padrão')
    expect(trigger(w, 'pref-new-effort').text()).toBe('Raciocínio padrão')
    expect(trigger(w, 'pref-new-mode').text()).toBe('Modo padrão')
  })
})

describe('preferências gerais: "Sem perguntas" como modo padrão', () => {
  const overlay = (w: Tab) => w.find('[data-test="bypass-overlay"]')

  it('escolher abre o diálogo de confirmação e nada muda até confirmar', async () => {
    stub({ new_session_mode: 'plan' })
    const w = await mountTab()
    await choose(w, 'pref-new-mode', 'Sem perguntas')
    expect(overlay(w).exists()).toBe(true)
    expect(w.find('[role="alertdialog"]').text()).toContain('sem pedir')
    expect(trigger(w, 'pref-new-mode').text()).toBe('Planejamento')
  })

  it('cancelar mantém o valor anterior', async () => {
    stub({ new_session_mode: 'plan' })
    const w = await mountTab()
    await choose(w, 'pref-new-mode', 'Sem perguntas')
    await w.find('[data-test="bypass-cancel"]').trigger('click')
    await flushPromises()
    expect(overlay(w).exists()).toBe(false)
    expect(trigger(w, 'pref-new-mode').text()).toBe('Planejamento')
    await w.find('form').trigger('submit')
    await flushPromises()
    expect(puts[0]).toMatchObject({ new_session_mode: 'plan' })
  })

  it('Esc e clique no fundo cancelam', async () => {
    stub({})
    const w = await mountTab()
    await choose(w, 'pref-new-mode', 'Sem perguntas')
    await w.find('[role="alertdialog"]').trigger('keydown', { key: 'Escape' })
    expect(overlay(w).exists()).toBe(false)
    await choose(w, 'pref-new-mode', 'Sem perguntas')
    await overlay(w).trigger('click')
    expect(overlay(w).exists()).toBe(false)
    expect(trigger(w, 'pref-new-mode').text()).toBe('Modo padrão')
  })

  it('confirmar define o modo, destaca o botão e o Salvar envia', async () => {
    stub({ editor_command: ['code'] })
    const w = await mountTab()
    expect(trigger(w, 'pref-new-mode').classes()).not.toContain('text-secondary')
    await choose(w, 'pref-new-mode', 'Sem perguntas')
    await w.find('[data-test="bypass-confirm"]').trigger('click')
    await flushPromises()
    expect(overlay(w).exists()).toBe(false)
    expect(trigger(w, 'pref-new-mode').text()).toBe('Sem perguntas')
    expect(trigger(w, 'pref-new-mode').classes()).toContain('text-secondary')
    expect(puts).toEqual([])
    await w.find('form').trigger('submit')
    await flushPromises()
    expect(puts).toHaveLength(1)
    expect(puts[0]).toMatchObject({ editor_command: ['code'], new_session_mode: 'bypassPermissions' })
  })

  it.each([['cancelar', 'bypass-cancel'], ['confirmar', 'bypass-confirm']])('ao %s o foco volta ao botão do modo', async (_, test) => {
    stub({})
    const w = await mountTab()
    await choose(w, 'pref-new-mode', 'Sem perguntas')
    await w.find(`[data-test="${test}"]`).trigger('click')
    await flushPromises()
    expect(document.activeElement).toBe(trigger(w, 'pref-new-mode').element)
  })

  it('reconhece o valor salvo, sem pedir confirmação', async () => {
    stub({ new_session_mode: 'bypassPermissions' })
    const w = await mountTab()
    expect(trigger(w, 'pref-new-mode').text()).toBe('Sem perguntas')
    expect(trigger(w, 'pref-new-mode').classes()).toContain('text-secondary')
    expect(overlay(w).exists()).toBe(false)
  })

  it('escolher outro modo depois não pede confirmação', async () => {
    stub({ new_session_mode: 'bypassPermissions' })
    const w = await mountTab()
    await choose(w, 'pref-new-mode', 'Pede permissão')
    expect(overlay(w).exists()).toBe(false)
    expect(trigger(w, 'pref-new-mode').text()).toBe('Pede permissão')
  })

  it('o texto de ajuda não diz mais que só se ativa na conversa', async () => {
    stub({})
    const w = await mountTab()
    expect(w.find('#pref-new-help').text()).not.toContain('só se ativa dentro da conversa')
    expect(w.find('#pref-new-help').text()).toContain('pede confirmação ao escolher')
  })
})

describe('preferências gerais: tamanho do texto', () => {
  const options = (w: Tab) => w.findAll('[data-test="ui-scale-option"]')
  const radio = (w: Tab, label: string) => {
    const opt = options(w).find((o) => o.text() === label)
    expect(opt, `opção ${label}`).toBeDefined()
    return opt!.find('input[type="radio"]')
  }

  it('mostra as seis opções, com 100% marcado por padrão', async () => {
    stub({})
    const w = await mountTab()
    expect(options(w).map((o) => o.text())).toEqual(['90%', '100%', '112%', '125%', '137%', '150%'])
    expect(w.findAll('input[type="radio"][name="ui-scale"]')).toHaveLength(6)
    const checked = w.findAll('input[name="ui-scale"]').filter((i) => (i.element as HTMLInputElement).checked)
    expect(checked).toHaveLength(1)
    expect((radio(w, '100%').element as HTMLInputElement).checked).toBe(true)
  })

  it('marca o tamanho atual', async () => {
    setUiScale(137.5)
    stub({})
    const w = await mountTab()
    expect((radio(w, '137%').element as HTMLInputElement).checked).toBe(true)
    expect((radio(w, '100%').element as HTMLInputElement).checked).toBe(false)
  })

  it('escolher 125% aplica e guarda na hora, sem chamar a API de salvar', async () => {
    stub({})
    const w = await mountTab()
    await radio(w, '125%').setValue(true)
    expect(uiScale.value).toBe(125)
    expect(document.documentElement.style.fontSize).toBe('125%')
    expect(localStorage.getItem('maestro:ui-scale')).toBe('125')
    expect(puts).toEqual([])
    expect((radio(w, '125%').element as HTMLInputElement).checked).toBe(true)
    await w.find('form').trigger('submit')
    await flushPromises()
    expect(puts[0]).not.toHaveProperty('ui_scale')
  })

  it('funciona mesmo quando as preferências do servidor não carregaram', async () => {
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/state': () => jsonResponse({ detail: 'Banco indisponível.' }, 500),
      'GET /api/models': () => jsonResponse(MODELS),
    }))
    const w = await mountTab()
    expect(w.find('[role="alert"]').exists()).toBe(true)
    expect(w.find('[data-test="save"]').attributes('disabled')).toBeDefined()
    const input = radio(w, '150%')
    expect(input.attributes('disabled')).toBeUndefined()
    expect(w.find('fieldset[disabled] input[name="ui-scale"]').exists()).toBe(false)
    await input.setValue(true)
    expect(document.documentElement.style.fontSize).toBe('150%')
    expect(localStorage.getItem('maestro:ui-scale')).toBe('150')
  })
})

describe('versão nas Preferências', () => {
  const RELEASES = 'https://github.com/vateiixeira/claudio-maestro/releases'
  const NOW = new Date(2026, 9, 5, 15, 0)
  const base = { enabled: true, current: '0.1.0', available: false, latest: null, checked_at: NOW.getTime() / 1000 - 7200, releases_url: RELEASES }
  beforeEach(() => { vi.useFakeTimers({ toFake: ['Date'] }); vi.setSystemTime(NOW); stub({}) })
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
