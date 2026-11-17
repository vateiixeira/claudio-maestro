import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import DigestAgentPreferences from '../DigestAgentPreferences.vue'
import { jsonResponse, routeFetch } from '../../../test/factories'
import { useDigestStore } from '../../../stores/digest'
import type { DigestConfig, DigestRun } from '../../../types/api'

enableAutoUnmount(afterEach)

const CONFIG: DigestConfig = {
  enabled: false, model: 'sonnet', effort: 'medium', extra_instructions: '',
  interval_minutes: 10, min_new_messages: 10, open_turn_minutes: 30, window_days: 3, closure_auto: true,
}
const STATUS = { enabled: false, running: false, next_run_at: null, paused_until: null }
const RUN: DigestRun = {
  id: 1, started_at: 1000, finished_at: 1010, trigger: 'auto', read_count: 2, skipped_count: 3,
  errors: [{ session_id: 's1', title: 'Sessão A', message: 'Resposta ruim.' }], stopped: null,
}

let pinia: Pinia
let puts: unknown[]
let runCalls: number
let runList: DigestRun[]

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  puts = []
  runCalls = 0
  runList = [RUN]
})
afterEach(() => vi.unstubAllGlobals())

function stub(put?: (body: DigestConfig) => Response) {
  vi.stubGlobal('fetch', routeFetch({
    'GET /api/digest/config': () => jsonResponse({ config: CONFIG, status: STATUS }),
    'PUT /api/digest/config': (init) => {
      const body = JSON.parse(String(init?.body)) as DigestConfig
      puts.push(body)
      return put ? put(body) : jsonResponse({ config: body, status: { ...STATUS, enabled: body.enabled } })
    },
    'POST /api/digest/run': () => { runCalls++; return jsonResponse({ ...STATUS, running: true }, 202) },
    'GET /api/digest/runs': () => jsonResponse(runList),
    'GET /api/models': () => jsonResponse([{ value: 'sonnet', displayName: 'Sonnet' }, { value: 'haiku', displayName: 'Haiku' }]),
  }))
}

async function mountTab() {
  const w = mount(DigestAgentPreferences, { global: { plugins: [pinia] } })
  await flushPromises()
  return w
}

describe('aba do agente de resumos', () => {
  it('mostra a configuração salva e o estado', async () => {
    stub()
    const w = await mountTab()
    expect(w.find('#digest-enabled').attributes('aria-checked')).toBe('false')
    expect((w.find('#digest-model').element as HTMLSelectElement).value).toBe('sonnet')
    expect((w.find('#digest-effort').element as HTMLSelectElement).value).toBe('medium')
    expect((w.find('#digest-interval').element as HTMLInputElement).value).toBe('10')
    expect(w.find('[data-test="digest-status"]').text()).toBe('Desligado')
  })

  it('salva o formulário inteiro', async () => {
    stub()
    const w = await mountTab()
    await w.find('#digest-enabled').trigger('click')
    await w.find('#digest-model').setValue('haiku')
    await w.find('#digest-instructions').setValue('Cite a tarefa.')
    await w.find('#digest-window').setValue('7')
    await w.find('form').trigger('submit')
    await flushPromises()
    expect(puts).toEqual([{ ...CONFIG, enabled: true, model: 'haiku', extra_instructions: 'Cite a tarefa.', window_days: 7 }])
    expect(w.find('[data-test="digest-saved"]').exists()).toBe(true)
  })

  it('mostra a chave de verificação de entrega e salva o valor novo', async () => {
    stub()
    const w = await mountTab()
    const toggle = w.get('#digest-closure-auto')
    expect(toggle.attributes('role')).toBe('switch')
    expect(toggle.attributes('aria-checked')).toBe('true')
    expect(w.text()).toContain('Verificar entrega automaticamente')
    expect(w.text()).toContain('Desligada, a verificação só roda pelo Resumir agora.')
    await toggle.trigger('click')
    expect(toggle.attributes('aria-checked')).toBe('false')
    await w.find('form').trigger('submit')
    await flushPromises()
    expect(puts).toEqual([{ ...CONFIG, closure_auto: false }])
  })

  it('as chaves de ligado e de verificação são switches que alternam o formulário', async () => {
    stub()
    const w = await mountTab()
    for (const id of ['#digest-enabled', '#digest-closure-auto']) {
      const sw = w.get(id)
      expect(sw.attributes('role')).toBe('switch')
      expect(sw.attributes('aria-label')).toBeTruthy()
      const before = sw.attributes('aria-checked')
      await sw.trigger('click')
      expect(sw.attributes('aria-checked')).toBe(before === 'true' ? 'false' : 'true')
    }
  })

  it('escreve as quatro regras como frases com o campo no meio', async () => {
    stub()
    const w = await mountTab()
    const rules = w.findAll('[data-test="digest-rule"]')
    expect(rules).toHaveLength(4)
    const expected: [string, string][] = [
      ['#digest-interval', 'Passa a cada … minutos.'],
      ['#digest-min', 'Relê uma conversa quando ela tem pelo menos … mensagens novas e o turno terminou,'],
      ['#digest-open-turn', 'ou quando o turno está aberto há mais de … minutos.'],
      ['#digest-window', 'Ignora conversas finalizadas ou paradas há mais de … dias.'],
    ]
    expected.forEach(([id, text], i) => {
      const field = rules[i].get(id)
      expect(field.attributes('aria-label')).toBeTruthy()
      const clone = rules[i].element.cloneNode(true) as HTMLElement
      clone.querySelectorAll('input').forEach((el) => el.replaceWith('…'))
      expect(clone.textContent?.replace(/\s+/g, ' ').trim()).toBe(text)
    })
  })

  it('mostra o estado e Rodar agora antes das regras, e o aviso da assinatura', async () => {
    stub()
    const w = await mountTab()
    const html = w.html()
    const pos = (marker: string) => html.indexOf(marker)
    expect(pos('data-test="digest-status"')).toBeGreaterThan(-1)
    expect(pos('data-test="digest-status"')).toBeLessThan(pos('data-test="digest-rule"'))
    expect(pos('data-test="digest-run"')).toBeLessThan(pos('data-test="digest-rule"'))
    expect(w.text()).toContain('Cada leitura usa a sua assinatura.')
  })

  it('valida no navegador sem chamar o servidor', async () => {
    stub()
    const w = await mountTab()
    await w.find('#digest-interval').setValue('1')
    await w.find('form').trigger('submit')
    await flushPromises()
    expect(puts).toEqual([])
    expect(w.find('[role="alert"]').text()).toBe('O intervalo precisa ser um número inteiro de 2 a 240 minutos.')
  })

  it('mostra o erro do servidor', async () => {
    stub(() => jsonResponse({ detail: 'Escolha um modelo da lista.' }, 422))
    const w = await mountTab()
    await w.find('form').trigger('submit')
    await flushPromises()
    expect(w.find('[role="alert"]').text()).toContain('Escolha um modelo da lista.')
  })

  it('rodar agora chama a rota e fica desabilitado enquanto roda', async () => {
    stub()
    const w = await mountTab()
    await w.find('[data-test="digest-run"]').trigger('click')
    await flushPromises()
    expect(runCalls).toBe(1)
    useDigestStore().applyStatus({ ...STATUS, running: true })
    await flushPromises()
    expect(w.find('[data-test="digest-run"]').attributes('disabled')).toBeDefined()
    expect(w.find('[data-test="digest-status"]').text()).toBe('Rodando…')
  })

  it('lista as passadas e abre os erros', async () => {
    stub()
    const w = await mountTab()
    const row = w.find('[data-test="digest-run-row"]')
    expect(row.text()).toContain('2')
    expect(row.text()).toContain('3')
    expect(w.find('[data-test="digest-run-details"]').exists()).toBe(false)
    await w.find('[data-test="digest-run-toggle"]').trigger('click')
    expect(w.find('[data-test="digest-run-details"]').text()).toContain('Sessão A: Resposta ruim.')
  })

  it('rotula as passadas da verificação automática de fechamento', async () => {
    runList = [{ ...RUN, trigger: 'auto_closure' }]
    stub()
    const w = await mountTab()
    expect(w.find('[data-test="digest-run-row"]').text()).toContain('Verificação automática')
  })

  it('recarrega o registro quando uma passada termina', async () => {
    stub()
    const w = await mountTab()
    const store = useDigestStore()
    store.applyStatus({ ...STATUS, running: true })
    await flushPromises()
    const before = vi.mocked(fetch).mock.calls.filter(([url]) => url === '/api/digest/runs').length
    store.applyStatus({ ...STATUS, running: false })
    await flushPromises()
    const after = vi.mocked(fetch).mock.calls.filter(([url]) => url === '/api/digest/runs').length
    expect(after).toBe(before + 1)
    expect(w.exists()).toBe(true)
  })
})
