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
let contextCalls = 0
const contextRequests = () => contextCalls

const BREAKDOWN = {
  available: true,
  context: { used_tokens: 84_800, max_tokens: 400_000, percent: 21.2 },
  breakdown: {
    model: 'claude-opus-5-5', total_tokens: 84_800, max_tokens: 400_000, percent: 21.2,
    categories: [
      { name: 'Messages', tokens: 35_800, kind: 'used' },
      { name: 'System tools', tokens: 12_000, kind: 'used' },
      { name: 'Free space', tokens: 300_000, kind: 'free' },
    ],
    mcp_tools: [], memory_files: [], agents: [], skills: [],
  },
}

function setup(options: Record<string, unknown> = {}, patchStatus = 200) {
  pinia = createPinia()
  setActivePinia(pinia)
  patches = []
  contextCalls = 0
  const store = useConversationStore(pinia)
  store.bySession['s1'] = conversationFromSnapshot({
    ...makeSnapshot({ seq: 1 }),
    model: 'sonnet', model_resolved: 'claude-sonnet-5-20260901', effort: 'medium', permission_mode: 'acceptEdits', effort_pending: false,
    ...options,
  } as never)
  const fetchMock = routeFetch({
    'GET /api/models': () => jsonResponse(MODELS),
    'GET /api/claude-cli': () => jsonResponse(CLAUDE_CLI),
    'GET /api/sessions/s1/context': () => { contextCalls++; return jsonResponse(BREAKDOWN) },
    'PATCH /api/sessions/s1': (init) => {
      const body = JSON.parse(init!.body as string)
      patches.push(body)
      if (patchStatus !== 200) return jsonResponse({ detail: 'Não deu.' }, patchStatus)
      const remote = typeof body.remote_control === 'boolean'
        ? { remote_control_state: body.remote_control ? 'on' : 'off', remote_control_url: body.remote_control ? 'https://claude.ai/code/session_1' : null, remote_control_error: null }
        : {}
      return jsonResponse({ ...makeSession(), model: 'sonnet', effort: 'medium', permission_mode: 'acceptEdits', effort_pending: false, model_resolved: null, ...remote, ...body })
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
  const popover = () => body().find('[data-test="context-popover"]')

  it('mostra o indicador com qualquer percentual, discreto abaixo de 80%', async () => {
    setup({ context: { used_tokens: 84_000, max_tokens: 200_000, percent: 21 } })
    const el = contextText(await mountControls())
    expect(el.exists()).toBe(true)
    expect(el.element.tagName).toBe('BUTTON')
    expect(el.text()).toBe('21%')
    expect(el.classes()).toContain('text-fg-subtle')
    expect(el.classes()).not.toContain('text-secondary')
  })

  it('destaca com text-secondary a partir de 80%', async () => {
    setup({ context: { used_tokens: 170_000, max_tokens: 200_000, percent: 84 } })
    const el = contextText(await mountControls())
    expect(el.text()).toBe('84%')
    expect(el.classes()).toContain('text-secondary')
    expect(el.classes()).not.toContain('text-fg-subtle')
  })

  it('80% já destaca', async () => {
    setup({ context: { used_tokens: 160_000, max_tokens: 200_000, percent: 80 } })
    expect(contextText(await mountControls()).classes()).toContain('text-secondary')
  })

  it('o leitor de tela ouve percentual e tokens; o texto visível não é lido de novo', async () => {
    setup({ context: { used_tokens: 170_000, max_tokens: 200_000, percent: 85 } })
    const el = contextText(await mountControls())
    expect(el.attributes('aria-label')).toBe('Contexto 85%, 170 mil de 200 mil tokens')
    expect(el.attributes('title')).toBe('170 mil de 200 mil tokens')
    expect(el.attributes('aria-haspopup')).toBe('dialog')
    expect(el.attributes('aria-expanded')).toBe('false')
  })

  it('arredonda a porcentagem e formata milhões', async () => {
    setup({ context: { used_tokens: 850_000, max_tokens: 1_000_000, percent: 85.4 } })
    const el = contextText(await mountControls())
    expect(el.text()).toBe('85%')
    expect(el.attributes('title')).toBe('850 mil de 1 milhão de tokens')
  })

  it('sem contexto não há indicador', async () => {
    setup({ context: null })
    const w = await mountControls()
    expect(contextText(w).exists()).toBe(false)
    expect(popover().exists()).toBe(false)
  })

  it('o resumo da sessão mais novo vence o retrato', async () => {
    setup({ context: { used_tokens: 84_000, max_tokens: 200_000, percent: 85 } })
    useSessionsStore(pinia).setForProject(1, [
      makeSession({ session_id: 's1', context: { used_tokens: 120_000, max_tokens: 200_000, percent: 90 } }),
    ])
    expect(contextText(await mountControls()).text()).toBe('90%')
  })

  it('lista com contexto nulo cai no valor do retrato', async () => {
    setup({ context: { used_tokens: 170_000, max_tokens: 200_000, percent: 85 } })
    useSessionsStore(pinia).setForProject(1, [makeSession({ session_id: 's1', context: null })])
    expect(contextText(await mountControls()).text()).toBe('85%')
  })

  it('lista com contexto e retrato sem contexto mostra o da lista', async () => {
    setup({ context: null })
    useSessionsStore(pinia).setForProject(1, [
      makeSession({ session_id: 's1', context: { used_tokens: 120_000, max_tokens: 200_000, percent: 90 } }),
    ])
    expect(contextText(await mountControls()).text()).toBe('90%')
  })

  describe('popover', () => {
    beforeEach(() => setup({ context: { used_tokens: 84_800, max_tokens: 400_000, percent: 21.2 } }))

    it('começa fechado e sem pedir o detalhamento', async () => {
      const w = await mountControls()
      expect(popover().exists()).toBe(false)
      expect(contextRequests()).toBe(0)
      expect(contextText(w).attributes('aria-expanded')).toBe('false')
    })

    it('o indicador abre o popover com o detalhamento', async () => {
      const w = await mountControls()
      await contextText(w).trigger('click')
      await flushPromises()
      expect(contextText(w).attributes('aria-expanded')).toBe('true')
      expect(popover().exists()).toBe(true)
      expect(popover().attributes('role')).toBe('dialog')
      expect(popover().find('[data-test="ctx-root"]').attributes('data-variant')).toBe('popover')
      expect(popover().find('[data-test="ctx-percent"]').text()).toBe('21% usado')
      expect(popover().findAll('[data-test="ctx-row"]').length).toBeGreaterThan(0)
      expect(contextRequests()).toBe(1)
    })

    it('clicar de novo no indicador fecha', async () => {
      const w = await mountControls()
      await contextText(w).trigger('click')
      await contextText(w).trigger('click')
      expect(popover().exists()).toBe(false)
      expect(contextText(w).attributes('aria-expanded')).toBe('false')
    })

    it('Esc fecha o popover e devolve o foco ao indicador', async () => {
      const w = await mountControls()
      await contextText(w).trigger('click')
      await flushPromises()
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }))
      await flushPromises()
      expect(popover().exists()).toBe(false)
      expect(document.activeElement).toBe(contextText(w).element)
    })

    it('clique fora fecha sem roubar o foco; clique dentro não fecha', async () => {
      const w = await mountControls()
      await contextText(w).trigger('click')
      await flushPromises()
      popover().element.dispatchEvent(new Event('pointerdown', { bubbles: true }))
      await flushPromises()
      expect(popover().exists()).toBe(true)
      document.body.dispatchEvent(new Event('pointerdown', { bubbles: true }))
      await flushPromises()
      expect(popover().exists()).toBe(false)
    })

    it('o Esc com o popover aberto não chega aos outros ouvintes da página', async () => {
      const w = await mountControls()
      const seen = vi.fn()
      window.addEventListener('keydown', seen)
      try {
        await contextText(w).trigger('click')
        await flushPromises()
        popover().element.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }))
        await flushPromises()
        expect(popover().exists()).toBe(false)
        expect(seen).not.toHaveBeenCalled()
      } finally {
        window.removeEventListener('keydown', seen)
      }
    })

    it('com o popover fechado nenhum ouvinte de Esc fica preso', async () => {
      const w = await mountControls()
      await contextText(w).trigger('click')
      await contextText(w).trigger('click')
      const event = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
      document.dispatchEvent(event)
      expect(event.defaultPrevented).toBe(false)
    })
  })
})

describe('Remote Control', () => {
  const rc = (w: ReturnType<typeof mount>) => w.find('button[aria-label^="Remote Control"]')

  it('é o primeiro item da barra', async () => {
    setup()
    const w = await mountControls()
    const first = w.find('button')
    expect(first.attributes('aria-label')).toMatch(/^Remote Control/)
    expect(first.text()).toBe('Remote Control')
  })

  it('desligado: o clique manda PATCH com remote_control true e aplica a resposta', async () => {
    setup()
    const w = await mountControls()
    await rc(w).trigger('click')
    await flushPromises()
    expect(patches).toEqual([{ remote_control: true }])
    // The PATCH response (a full session) carries the new state.
    expect(rc(w).attributes('title')).toContain('Remote Control ativo')
  })

  it('o estado vem de session.options: ligado fica azul e abre o menu', async () => {
    const { store } = setup({ remote_control: true, remote_control_state: 'connecting' })
    const w = await mountControls()
    expect(rc(w).attributes('title')).toBe('Remote Control conectando…')
    store.receive(makeEvent('session.options', {
      model: 'sonnet', model_resolved: null, effort: 'medium', permission_mode: 'acceptEdits', effort_pending: false,
      remote_control: true, remote_control_state: 'on', remote_control_url: 'https://claude.ai/code/session_1', remote_control_error: null,
    }, 2))
    await flushPromises()
    expect(rc(w).classes()).toContain('text-info-soft')
    await rc(w).trigger('click')
    expect(body().find('[role="menu"] a[href="https://claude.ai/code/session_1"]').exists()).toBe(true)
    await body().findAll('[role="menu"] [role="menuitem"]').at(-1)!.trigger('click')
    await flushPromises()
    expect(patches).toEqual([{ remote_control: false }])
  })

  it('marca ligada com estado off (sem processo) aparece como conectando, sem azul', async () => {
    setup({ remote_control: true, remote_control_state: 'off' })
    const w = await mountControls()
    expect(rc(w).attributes('title')).toBe('Remote Control conectando…')
    expect(rc(w).classes()).not.toContain('text-info-soft')
  })

  it('falhou mostra o erro no aviso do chip', async () => {
    setup({ remote_control: true, remote_control_state: 'failed', remote_control_error: 'sem rede' })
    const w = await mountControls()
    expect(rc(w).attributes('title')).toBe('Remote Control não conectou: sem rede. Tentando de novo.')
  })

  it('depois de ligar, o foco volta ao chip (ele fica desabilitado durante o PATCH)', async () => {
    setup()
    const w = await mountControls()
    ;(rc(w).element as HTMLElement).focus()
    const click = rc(w).trigger('click')
    // The browser drops the focus of a button that becomes disabled (jsdom does not, and cannot blur it afterwards).
    ;(document.activeElement as HTMLElement | null)?.blur()
    await click
    await flushPromises()
    expect(document.activeElement).toBe(rc(w).element)
  })

  it('o 409 mostra o detail no erro da barra', async () => {
    setup({}, 409)
    const w = await mountControls()
    await rc(w).trigger('click')
    await flushPromises()
    expect(w.find('[role="alert"]').text()).toContain('Não deu.')
  })

  it('sessão concluída: o chip fica desabilitado', async () => {
    const { store } = setup()
    void store
    useSessionsStore(pinia).setForProject(1, [makeSession({ session_id: 's1', finished: true })])
    const w = await mountControls()
    expect(rc(w).attributes('disabled')).toBeDefined()
    expect(rc(w).attributes('title')).toBe('Reabra a sessão para ligar o Remote Control')
    await rc(w).trigger('click')
    expect(patches).toEqual([])
  })
})

describe('sessão de agente', () => {
  const EXPLANATION = 'Sessões de agente ficam no modo padrão; as ações para fora seguem a autonomia do agente.'

  it('o seletor de modo fica desabilitado, com a explicação', async () => {
    setup()
    useSessionsStore(pinia).setForProject(1, [makeSession({ session_id: 's1', agent_id: 3 })])
    const w = await mountControls()
    expect(button(w, 'Permissões').attributes('disabled')).toBeDefined()
    expect(button(w, 'Permissões').attributes('title')).toBe(EXPLANATION)
    await button(w, 'Permissões').trigger('click')
    expect(body().find('[role="menu"]').exists()).toBe(false)
    expect(patches).toEqual([])
    // os outros seletores seguem ativos
    expect(button(w, 'Modelo').attributes('disabled')).toBeUndefined()
  })

  it('numa sessão comum o seletor de modo continua ativo e sem a explicação', async () => {
    setup()
    useSessionsStore(pinia).setForProject(1, [makeSession({ session_id: 's1', agent_id: null })])
    const w = await mountControls()
    expect(button(w, 'Permissões').attributes('disabled')).toBeUndefined()
    expect(button(w, 'Permissões').attributes('title')).toBeUndefined()
  })
})
