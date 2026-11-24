import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { DOMWrapper, enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import ConversationPreferences from '../ConversationPreferences.vue'
import { jsonResponse, routeFetch } from '../../../test/factories'
import { useModelsStore } from '../../../stores/models'

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
  useModelsStore(pinia)
  const w = mount(ConversationPreferences, { global: { plugins: [pinia], stubs: { ClaudeProfilePreferences: true } }, attachTo: document.body })
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

describe('preferências de conversas: padrões das conversas novas', () => {
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
      new_session_model: 'sonnet', new_session_effort: 'medium', new_session_mode: 'acceptEdits', kimi_enabled: false,
      kimi_new_session_model: null, kimi_new_session_effort: null,
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
    expect(puts[0]).toMatchObject({ new_session_model: null, new_session_effort: null, new_session_mode: null, kimi_enabled: false })
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

describe('preferências de conversas: "Sem perguntas" como modo padrão', () => {
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

  it('Esc cancela, mas clicar no fundo mantém a confirmação aberta', async () => {
    stub({})
    const w = await mountTab()
    await choose(w, 'pref-new-mode', 'Sem perguntas')
    await w.find('[role="alertdialog"]').trigger('keydown', { key: 'Escape' })
    expect(overlay(w).exists()).toBe(false)
    await choose(w, 'pref-new-mode', 'Sem perguntas')
    await overlay(w).trigger('click')
    expect(overlay(w).exists()).toBe(true)
    expect(trigger(w, 'pref-new-mode').text()).toBe('Modo padrão')
  })

  it('confirmar define o modo, destaca o botão e o Salvar envia', async () => {
    stub({ editor_command: ['code'] })
    const w = await mountTab()
    expect(trigger(w, 'pref-new-mode').classes()).not.toContain('text-secondary-soft')
    await choose(w, 'pref-new-mode', 'Sem perguntas')
    await w.find('[data-test="bypass-confirm"]').trigger('click')
    await flushPromises()
    expect(overlay(w).exists()).toBe(false)
    expect(trigger(w, 'pref-new-mode').text()).toBe('Sem perguntas')
    expect(trigger(w, 'pref-new-mode').classes()).toContain('text-secondary-soft')
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
    expect(trigger(w, 'pref-new-mode').classes()).toContain('text-secondary-soft')
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
