import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { DOMWrapper, enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import SessionControls from '../SessionControls.vue'
import { conversationFromSnapshot, useConversationStore } from '../../../stores/conversation'
import { useSessionsStore } from '../../../stores/sessions'
import { jsonResponse, makeEvent, makeSession, makeSnapshot, routeFetch } from '../../../test/factories'

enableAutoUnmount(afterEach)
afterEach(() => vi.unstubAllGlobals())

const MODELS = [
  { value: 'default', displayName: 'Padrão', description: 'Recomendado', supportsEffort: true, supportedEffortLevels: ['low', 'medium', 'high'] },
  { value: 'sonnet', displayName: 'Sonnet 5', description: 'Equilíbrio', supportsEffort: true, supportedEffortLevels: ['low', 'medium', 'high', 'xhigh', 'max'] },
  { value: 'haiku', displayName: 'Haiku', description: 'Rápido', supportsEffort: false },
]

const CLAUDE_CLI = {
  in_use: { source: 'system', version: '2.1.292' },
  system: { path: '/opt/bin/claude', version: '2.1.292' },
  bundled: { version: '2.1.284' },
  forced_bundled: false,
  can_update: true,
  job: null,
  latest: null,
  update_available: false,
}

let pinia: Pinia
let patches: unknown[]

function setup(options: Record<string, unknown> = {}, patchStatus = 200) {
  pinia = createPinia()
  setActivePinia(pinia)
  patches = []
  const store = useConversationStore(pinia)
  store.bySession['s1'] = conversationFromSnapshot({
    ...makeSnapshot({ seq: 1 }),
    model: 'sonnet', model_resolved: 'claude-sonnet-5-20260901', effort: 'medium', permission_mode: 'acceptEdits', effort_pending: false,
    ...options,
  } as never)
  const fetchMock = routeFetch({
    'GET /api/models': () => jsonResponse(MODELS),
    'GET /api/claude-cli': () => jsonResponse(CLAUDE_CLI),
    'PATCH /api/sessions/s1': (init) => {
      const body = JSON.parse(init!.body as string)
      patches.push(body)
      if (patchStatus !== 200) return jsonResponse({ detail: 'Não deu.' }, patchStatus)
      return jsonResponse({ ...makeSession(), model: 'sonnet', effort: 'medium', permission_mode: 'acceptEdits', effort_pending: false, model_resolved: null, ...body })
    },
  })
  vi.stubGlobal('fetch', fetchMock)
  return { store }
}

async function mountControls() {
  const w = mount(SessionControls, { props: { sessionId: 's1' }, global: { plugins: [pinia] }, attachTo: document.body })
  await flushPromises()
  return w
}
const button = (w: ReturnType<typeof mount>, prefix: string) => w.find(`button[aria-label^="${prefix}"]`)
// The option menus are teleported to <body>, outside the component wrapper.
const body = () => new DOMWrapper(document.body)
const labelOf = (item: DOMWrapper<Element>) => item.find('[data-test="option-label"]').text()

describe('seletores da sessão', () => {
  beforeEach(() => setup())

  it('mostra modelo, raciocínio e modo como no design', async () => {
    const w = await mountControls()
    expect(button(w, 'Modelo').text()).toBe('Sonnet 5')
    expect(button(w, 'Modelo').attributes('title')).toContain('claude-sonnet-5-20260901')
    expect(button(w, 'Raciocínio').text()).toBe('Raciocínio médio')
    expect(button(w, 'Permissões').text()).toBe('Permissões: Aceita edições')
  })

  it('lista os modelos da API num menu e troca com PATCH', async () => {
    const w = await mountControls()
    await button(w, 'Modelo').trigger('click')
    const items = body().findAll('[role="menu"] [role="menuitemradio"]')
    expect(items).toHaveLength(3)
    expect(items[1]!.text()).toContain('Sonnet 5')
    expect(items[1]!.text()).toContain('Equilíbrio')
    await items.find((i) => i.text().includes('Haiku'))!.trigger('click')
    await flushPromises()
    expect(patches).toEqual([{ model: 'haiku' }])
    expect(body().find('[role="menu"]').exists()).toBe(false)
  })

  it('foco volta ao seletor depois de salvar', async () => {
    const w = await mountControls()
    await button(w, 'Modelo').trigger('click')
    await body().findAll('[role="menuitemradio"]').find((i) => i.text().includes('Haiku'))!.trigger('click')
    await flushPromises()
    expect(document.activeElement).toBe(button(w, 'Modelo').element)
  })

  it('o menu de modelo tem o rodapé de atualização; raciocínio e permissões não', async () => {
    const w = await mountControls()
    await button(w, 'Modelo').trigger('click')
    await flushPromises()
    expect(body().find('[data-test="option-footer"]').exists()).toBe(true)
    expect(body().find('[data-test="claude-cli-update"]').text()).toContain('Atualizar o Claude')
    await body().find('[role="menu"]').trigger('keydown', { key: 'Escape' })
    expect(body().find('[role="menu"]').exists()).toBe(false)

    await button(w, 'Raciocínio').trigger('click')
    expect(body().find('[role="menu"]').exists()).toBe(true)
    expect(body().find('[data-test="option-footer"]').exists()).toBe(false)
    await body().find('[role="menu"]').trigger('keydown', { key: 'Escape' })

    await button(w, 'Permissões').trigger('click')
    expect(body().find('[role="menu"]').exists()).toBe(true)
    expect(body().find('[data-test="option-footer"]').exists()).toBe(false)
  })

  it('raciocínio só com os níveis do modelo e oculto se o modelo não suporta', async () => {
    const { store } = setup({ model: 'default' })
    const w = await mountControls()
    await button(w, 'Raciocínio').trigger('click')
    expect(body().findAll('[role="menuitemradio"]').map((i) => i.text())).toEqual(['Baixo', 'Médio', 'Alto'])
    store.get('s1')!.options.model = 'haiku'
    await flushPromises()
    expect(button(w, 'Raciocínio').exists()).toBe(false)
  })

  it('troca o raciocínio com PATCH', async () => {
    const w = await mountControls()
    await button(w, 'Raciocínio').trigger('click')
    await body().findAll('[role="menuitemradio"]').find((i) => labelOf(i) === 'Máximo')!.trigger('click')
    await flushPromises()
    expect(patches).toEqual([{ effort: 'max' }])
  })

  it('menu navega por setas e fecha com Esc', async () => {
    const w = await mountControls()
    const trigger = button(w, 'Permissões')
    await trigger.trigger('click')
    const items = body().findAll('[role="menuitemradio"]')
    expect(document.activeElement).toBe(items.find((i) => i.attributes('aria-checked') === 'true')!.element)
    await body().find('[role="menu"]').trigger('keydown', { key: 'ArrowDown' })
    expect(document.activeElement?.textContent?.trim()).toMatch(/^Planejamento/)
    await body().find('[role="menu"]').trigger('keydown', { key: 'Escape' })
    expect(body().find('[role="menu"]').exists()).toBe(false)
    expect(document.activeElement).toBe(trigger.element)
  })

  it('"Sem perguntas" pede confirmação antes do PATCH', async () => {
    const w = await mountControls()
    await button(w, 'Permissões').trigger('click')
    await body().findAll('[role="menuitemradio"]').find((i) => labelOf(i) === 'Sem perguntas')!.trigger('click')
    const dialog = w.find('[role="alertdialog"]')
    expect(dialog.exists()).toBe(true)
    expect(dialog.text()).toContain('sem pedir')
    expect(patches).toEqual([])
    await dialog.find('[data-test="bypass-cancel"]').trigger('click')
    expect(w.find('[role="alertdialog"]').exists()).toBe(false)
    expect(patches).toEqual([])

    await button(w, 'Permissões').trigger('click')
    await body().findAll('[role="menuitemradio"]').find((i) => labelOf(i) === 'Sem perguntas')!.trigger('click')
    await w.find('[data-test="bypass-confirm"]').trigger('click')
    await flushPromises()
    expect(patches).toEqual([{ permission_mode: 'bypassPermissions', confirm_bypass: true }])
  })

  it('"Sem perguntas" ativo fica destacado', async () => {
    setup({ permission_mode: 'bypassPermissions' })
    const w = await mountControls()
    expect(button(w, 'Permissões').text()).toBe('Permissões: Sem perguntas')
    expect(button(w, 'Permissões').classes()).toContain('text-secondary')
  })

  it('aplica session.options e mostra o pendente', async () => {
    const w = await mountControls()
    expect(w.text()).not.toContain('vale a partir do próximo turno')
    useConversationStore(pinia).receive(makeEvent('session.options', {
      model: 'default', model_resolved: null, effort: 'high', permission_mode: 'plan', effort_pending: true,
    }, 2))
    await flushPromises()
    expect(button(w, 'Modelo').text()).toBe('Padrão')
    expect(button(w, 'Raciocínio').text()).toBe('Raciocínio alto')
    expect(button(w, 'Permissões').text()).toBe('Permissões: Planejamento')
    expect(w.text()).toContain('vale a partir do próximo turno')
  })

  it('erro do PATCH aparece', async () => {
    setup({}, 400)
    const w = await mountControls()
    await button(w, 'Modelo').trigger('click')
    await body().findAll('[role="menuitemradio"]').find((i) => i.text().includes('Haiku'))!.trigger('click')
    await flushPromises()
    expect(w.find('[role="alert"]').text()).toContain('Não deu.')
    expect(w.find('[role="alert"]').classes()).toContain('text-diff-del-fg')
  })

  async function openBypass(w: ReturnType<typeof mount>) {
    const trigger = button(w, 'Permissões')
    ;(trigger.element as HTMLElement).focus()
    await trigger.trigger('click')
    await body().findAll('[role="menuitemradio"]').find((i) => labelOf(i) === 'Sem perguntas')!.trigger('click')
    await flushPromises()
    return trigger
  }

  it('diálogo prende Tab entre Cancelar e Ativar', async () => {
    const w = await mountControls()
    await openBypass(w)
    const cancel = w.find('[data-test="bypass-cancel"]').element
    const confirm = w.find('[data-test="bypass-confirm"]').element
    expect(document.activeElement).toBe(cancel)
    await w.find('[role="alertdialog"]').trigger('keydown', { key: 'Tab' })
    expect(document.activeElement).toBe(confirm)
    await w.find('[role="alertdialog"]').trigger('keydown', { key: 'Tab', shiftKey: true })
    expect(document.activeElement).toBe(cancel)
  })

  it('o foco inicial do diálogo vai para Cancelar, não para o botão perigoso', async () => {
    const w = await mountControls()
    await openBypass(w)
    expect(document.activeElement).toBe(w.find('[data-test="bypass-cancel"]').element)
  })

  for (const [how, act] of [
    ['cancelar', (w: ReturnType<typeof mount>) => w.find('[data-test="bypass-cancel"]').trigger('click')],
    ['confirmar', (w: ReturnType<typeof mount>) => w.find('[data-test="bypass-confirm"]').trigger('click')],
    ['Esc', (w: ReturnType<typeof mount>) => w.find('[role="alertdialog"]').trigger('keydown', { key: 'Escape' })],
    ['Esc no fundo', (w: ReturnType<typeof mount>) => w.find('[data-test="bypass-overlay"]').trigger('keydown', { key: 'Escape' })],
    ['clique no fundo', (w: ReturnType<typeof mount>) => w.find('[data-test="bypass-overlay"]').trigger('click')],
  ] as const) {
    it(`devolve o foco ao seletor de modo ao ${how}`, async () => {
      const w = await mountControls()
      const trigger = await openBypass(w)
      await act(w)
      await flushPromises()
      expect(w.find('[role="alertdialog"]').exists()).toBe(false)
      expect(document.activeElement).toBe(trigger.element)
    })
  }
})

describe('seletor de modo', () => {
  const MODE_ORDER = ['Pede permissão', 'Aceita edições', 'Planejamento', 'Sem perguntas', 'Automático', 'Só o pré-aprovado']

  it('mostra o rótulo "Permissões:" em tom suave antes do valor', async () => {
    setup()
    const w = await mountControls()
    const trigger = button(w, 'Permissões')
    expect(trigger.attributes('aria-label')).toBe('Permissões: aceita edições')
    const prefix = trigger.find('[data-test="option-prefix"]')
    expect(prefix.text()).toBe('Permissões:')
    expect(prefix.classes()).toContain('text-fg-subtle')
  })

  it('o rótulo de Modelo e Raciocínio não ganha prefixo extra', async () => {
    setup()
    const w = await mountControls()
    expect(button(w, 'Modelo').find('[data-test="option-prefix"]').exists()).toBe(false)
    expect(button(w, 'Raciocínio').find('[data-test="option-prefix"]').exists()).toBe(false)
  })

  it('cada modo tem uma descrição curta no menu', async () => {
    setup()
    const w = await mountControls()
    await button(w, 'Permissões').trigger('click')
    const items = body().findAll('[role="menuitemradio"]')
    expect(items.map(labelOf)).toEqual(MODE_ORDER)
    for (const item of items) {
      const description = item.find('[data-test="option-description"]').text()
      expect(description.length).toBeGreaterThan(10)
      expect(description.length).toBeLessThan(110)
    }
    const byLabel = (l: string) => items.find((i) => labelOf(i) === l)!.find('[data-test="option-description"]').text()
    expect(byLabel('Pede permissão')).toMatch(/pergunta/i)
    expect(byLabel('Aceita edições')).toContain('edições')
    expect(byLabel('Planejamento')).toContain('plano')
    expect(byLabel('Sem perguntas')).toContain('sem pedir')
    expect(byLabel('Só o pré-aprovado')).toContain('pré-aprovado')
  })

  it('o menu marca o modo atual com o check', async () => {
    setup()
    const w = await mountControls()
    await button(w, 'Permissões').trigger('click')
    const items = body().findAll('[role="menuitemradio"]')
    const checks = items.filter((i) => i.find('[data-test="option-check"]').exists())
    expect(checks).toHaveLength(1)
    expect(labelOf(checks[0]!)).toBe('Aceita edições')
    expect(checks[0]!.attributes('aria-checked')).toBe('true')
    expect(checks[0]!.find('svg').attributes('aria-hidden')).toBe('true')
  })

  it('"Sem perguntas" segue em laranja e com confirmação', async () => {
    setup({ permission_mode: 'bypassPermissions' })
    const w = await mountControls()
    const trigger = button(w, 'Permissões')
    expect(trigger.classes()).toContain('text-secondary')
    expect(trigger.classes()).toContain('bg-secondary-tint')
  })
})

describe('modos automático, só o pré-aprovado e desconhecido', () => {
  it('modo auto vindo do init não quebra e mostra o rótulo', async () => {
    setup({ permission_mode: 'auto' })
    const w = await mountControls()
    expect(button(w, 'Permissões').text()).toBe('Permissões: Automático')
  })

  it('modo desconhecido mostra o valor cru', async () => {
    setup({ permission_mode: 'novoModo' })
    const w = await mountControls()
    expect(button(w, 'Permissões').text()).toBe('Permissões: novoModo')
  })

  it.each([['Automático', 'auto'], ['Só o pré-aprovado', 'dontAsk']])('%s troca sem confirmação', async (label, value) => {
    setup()
    const w = await mountControls()
    await button(w, 'Permissões').trigger('click')
    await body().findAll('[role="menuitemradio"]').find((i) => labelOf(i) === label)!.trigger('click')
    await flushPromises()
    expect(w.find('[data-test="bypass-overlay"]').exists()).toBe(false)
    expect(patches).toEqual([{ permission_mode: value }])
  })
})

describe('resposta do PATCH', () => {
  it('não sobrescreve session.options que chegou depois do disparo', async () => {
    setup()
    let release: (r: Response) => void = () => {}
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/models': () => jsonResponse(MODELS),
      'PATCH /api/sessions/s1': () => new Promise<Response>((r) => { release = r }),
    }))
    const w = await mountControls()
    await button(w, 'Modelo').trigger('click')
    await body().findAll('[role="menuitemradio"]').find((i) => i.text().includes('Haiku'))!.trigger('click')
    await flushPromises()
    useConversationStore(pinia).receive(makeEvent('session.options', {
      model: 'haiku', model_resolved: null, effort: 'medium', permission_mode: 'plan', effort_pending: false,
    }, 2))
    release(jsonResponse({ ...makeSession(), model: 'haiku', effort: 'medium', permission_mode: 'acceptEdits', effort_pending: false, model_resolved: null }))
    await flushPromises()
    expect(button(w, 'Permissões').text()).toBe('Permissões: Planejamento')
  })
})

describe('uso do contexto', () => {
  const contextText = (w: ReturnType<typeof mount>) => w.find('[data-test="context-usage"]')

  it('esconde o contexto abaixo de 80%', async () => {
    setup({ context: { used_tokens: 84_000, max_tokens: 200_000, percent: 42 } })
    const w = await mountControls()
    expect(contextText(w).exists()).toBe(false)
    expect(w.find('[data-test="context-usage-sr"]').exists()).toBe(false)
  })

  it('mostra a porcentagem com os tokens no título a partir de 80%', async () => {
    setup({ context: { used_tokens: 170_000, max_tokens: 200_000, percent: 85 } })
    const w = await mountControls()
    const el = contextText(w)
    expect(el.text()).toBe('Contexto 85%')
    expect(el.attributes('title')).toBe('170 mil de 200 mil tokens')
    // Screen readers get the tokens too, not only the tooltip; the visible text is not read twice.
    expect(el.attributes('aria-hidden')).toBe('true')
    expect(w.find('[data-test="context-usage-sr"]').text()).toBe('Contexto 85%, 170 mil de 200 mil tokens')
    expect(w.find('[data-test="context-usage-sr"]').classes()).toContain('sr-only')
  })

  it('usa cor de alerta a partir de 80%', async () => {
    setup({ context: { used_tokens: 160_000, max_tokens: 200_000, percent: 80 } })
    expect(contextText(await mountControls()).classes()).toContain('text-secondary')
  })

  it('arredonda a porcentagem e formata milhões', async () => {
    setup({ context: { used_tokens: 850_000, max_tokens: 1_000_000, percent: 85.4 } })
    const el = contextText(await mountControls())
    expect(el.text()).toBe('Contexto 85%')
    expect(el.attributes('title')).toBe('850 mil de 1 milhão de tokens')
  })

  it('não mostra nada sem contexto', async () => {
    setup({ context: null })
    expect(contextText(await mountControls()).exists()).toBe(false)
  })

  it('o resumo da sessão mais novo vence o retrato', async () => {
    setup({ context: { used_tokens: 84_000, max_tokens: 200_000, percent: 85 } })
    useSessionsStore(pinia).setForProject(1, [
      makeSession({ session_id: 's1', context: { used_tokens: 120_000, max_tokens: 200_000, percent: 90 } }),
    ])
    expect(contextText(await mountControls()).text()).toBe('Contexto 90%')
  })

  it('lista com contexto nulo cai no valor do retrato', async () => {
    setup({ context: { used_tokens: 170_000, max_tokens: 200_000, percent: 85 } })
    useSessionsStore(pinia).setForProject(1, [makeSession({ session_id: 's1', context: null })])
    expect(contextText(await mountControls()).text()).toBe('Contexto 85%')
  })

  it('lista com contexto e retrato sem contexto mostra o da lista', async () => {
    setup({ context: null })
    useSessionsStore(pinia).setForProject(1, [
      makeSession({ session_id: 's1', context: { used_tokens: 120_000, max_tokens: 200_000, percent: 90 } }),
    ])
    expect(contextText(await mountControls()).text()).toBe('Contexto 90%')
  })
})
