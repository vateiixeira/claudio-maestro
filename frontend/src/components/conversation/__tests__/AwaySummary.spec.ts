import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import AwaySummary from '../AwaySummary.vue'
import { jsonResponse, routeFetch } from '../../../test/factories'
import { useDigestStore } from '../../../stores/digest'
import type { DigestStatus, SessionDigest } from '../../../types/api'

enableAutoUnmount(afterEach)

// Midday: relative times like "há 2 min" must stay on the same day whatever time the suite runs.
const MIDDAY = new Date(2026, 9, 3, 12, 0, 0)
const NOW = Math.floor(MIDDAY.getTime() / 1000)
const SINCE = NOW - 42 * 60
const COUNTS = { turns: 2, actions: 14, files: 3 }

const DIGEST: SessionDigest = {
  session_id: 's1', read_at: NOW - 300, short: 'Executa o plano', plan_done: false, error: null, error_at: null,
  phases: [
    { title: 'Plano', kind: 'plan', status: 'done', done: ['Tarefa 1: tabela'], pending: [], ref: null },
    { title: 'Ajustes', kind: 'adjustments', status: 'open', done: ['Menu ordenado'], pending: ['Ordenar por nome', 'Testar o filtro'], ref: null },
  ],
}
const ON: DigestStatus = { enabled: true, running: false, next_run_at: null, paused_until: null }
const OFF: DigestStatus = { enabled: false, running: false, next_run_at: null, paused_until: null }

let pinia: Pinia
let posts: number
let modelCalls: number

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(MIDDAY)
  pinia = createPinia()
  setActivePinia(pinia)
  posts = 0
  modelCalls = 0
})
afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

function stub(status: DigestStatus, digest: SessionDigest | null) {
  useDigestStore(pinia).status = status
  vi.stubGlobal('fetch', routeFetch({
    'GET /api/sessions/s1/digest': () => jsonResponse(digest),
    'GET /api/digest/config': () => jsonResponse({ config: {}, status }),
    'POST /api/sessions/s1/digest': () => { posts++; modelCalls++; return jsonResponse({ queued: true }, 202) },
  }))
}

async function mountCard(counts = COUNTS) {
  const w = mount(AwaySummary, { props: { sessionId: 's1', since: SINCE, counts }, global: { plugins: [pinia] } })
  await flushPromises()
  return w
}

describe('card "Enquanto você estava fora"', () => {
  it('mostra o cabeçalho com há quanto tempo e as contagens', async () => {
    stub(OFF, null)
    const w = await mountCard()
    expect(w.find('[data-test="away-title"]').text()).toBe('Enquanto você estava fora · há 42 min')
    expect(w.find('[data-test="away-title"]').classes()).toContain('cap')
    expect(w.find('[data-test="away-counts"]').text()).toBe('2 turnos · 14 ações · 3 arquivos alterados')
  })

  it('usa o singular e esconde o que é zero', async () => {
    stub(OFF, null)
    const w = await mountCard({ turns: 1, actions: 1, files: 0 })
    expect(w.find('[data-test="away-counts"]').text()).toBe('1 turno · 1 ação')
  })

  it('usa a aparência de painel do desenho', async () => {
    stub(OFF, null)
    const w = await mountCard()
    const root = w.find('[data-test="away-summary"]')
    expect(root.classes()).toEqual(expect.arrayContaining(['bg-panel', 'border-line-strong', 'rounded-xl']))
  })

  it('o × avisa que foi fechado', async () => {
    stub(OFF, null)
    const w = await mountCard()
    const close = w.find('[data-test="away-close"]')
    expect(close.attributes('aria-label')).toBe('Fechar')
    await close.trigger('click')
    expect(w.emitted('close')).toHaveLength(1)
  })

  it('"Ver alterações" e "Ir para o fim" avisam quem montou o card', async () => {
    stub(OFF, null)
    const w = await mountCard()
    await w.find('[data-test="away-view-changes"]').trigger('click')
    await w.find('[data-test="away-jump"]').trigger('click')
    expect(w.emitted('view-changes')).toHaveLength(1)
    expect(w.emitted('jump-to-end')).toHaveLength(1)
  })

  describe('com o resumo ligado', () => {
    it('mostra Feito e Falta tirados do resumo, com a idade do resumo', async () => {
      stub(ON, DIGEST)
      const w = await mountCard()
      const done = w.find('[data-test="away-done"]')
      const pending = w.find('[data-test="away-pending"]')
      expect(done.text()).toContain('Feito')
      expect(done.text()).toContain('Tarefa 1: tabela')
      expect(done.text()).toContain('Menu ordenado')
      expect(done.classes()).toContain('text-fg-muted')
      expect(pending.text()).toContain('Falta')
      expect(pending.text()).toContain('Ordenar por nome')
      expect(pending.text()).toContain('Testar o filtro')
      expect(pending.classes()).toContain('text-fg')
      expect(pending.find('[data-test="away-pending-title"]').classes()).toContain('text-secondary-soft')
      expect(w.find('[data-test="away-digest-age"]').text()).toBe('Resumo de há 5 min')
    })

    it('limita cada coluna e conta o resto', async () => {
      const many = Array.from({ length: 7 }, (_, i) => `Item ${i + 1}`)
      stub(ON, { ...DIGEST, phases: [{ title: 'Ajustes', kind: 'adjustments', status: 'open', done: many, pending: [], ref: null }] })
      const w = await mountCard()
      expect(w.findAll('[data-test="away-done"] li')).toHaveLength(4)
      expect(w.find('[data-test="away-done"]').text()).toContain('Item 7')
      expect(w.find('[data-test="away-done"]').text()).not.toContain('Item 1')
      expect(w.find('[data-test="away-done-more"]').text()).toBe('+ 3 antes')
    })

    it('sem nada pendente a coluna Falta diz isso', async () => {
      stub(ON, { ...DIGEST, phases: [DIGEST.phases[0]] })
      const w = await mountCard()
      expect(w.find('[data-test="away-pending"]').text()).toContain('Nada pendente')
    })

    it('nunca roda o modelo sozinho, mesmo sem resumo', async () => {
      stub(ON, null)
      await mountCard()
      expect(modelCalls).toBe(0)
    })

    it('sem resumo ainda mostra só as contagens e "Resumir agora"', async () => {
      stub(ON, null)
      const w = await mountCard()
      expect(w.find('[data-test="away-done"]').exists()).toBe(false)
      expect(w.find('[data-test="away-pending"]').exists()).toBe(false)
      expect(w.find('[data-test="away-digest-request"]').text()).toBe('Resumir agora')
    })
  })

  describe('com o resumo desligado', () => {
    it('mostra só as contagens e "Resumir agora", mesmo com resumo antigo guardado', async () => {
      stub(OFF, DIGEST)
      const w = await mountCard()
      expect(w.find('[data-test="away-counts"]').exists()).toBe(true)
      expect(w.find('[data-test="away-done"]').exists()).toBe(false)
      expect(w.find('[data-test="away-pending"]').exists()).toBe(false)
      expect(w.find('[data-test="away-digest-request"]').text()).toBe('Resumir agora')
    })

    it('não chama o modelo ao abrir, só ao clicar', async () => {
      stub(OFF, null)
      const w = await mountCard()
      expect(posts).toBe(0)
      await w.find('[data-test="away-digest-request"]').trigger('click')
      await flushPromises()
      expect(posts).toBe(1)
      const button = w.find('[data-test="away-digest-request"]')
      expect(button.text()).toBe('Resumindo…')
      expect(button.attributes('disabled')).toBeDefined()
    })
  })

  it('lê o estado do agente quando ainda não sabe', async () => {
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/sessions/s1/digest': () => jsonResponse(DIGEST),
      'GET /api/digest/config': () => jsonResponse({ config: {}, status: ON }),
    }))
    const w = await mountCard()
    expect(useDigestStore(pinia).status?.enabled).toBe(true)
    expect(w.find('[data-test="away-done"]').exists()).toBe(true)
  })
})
