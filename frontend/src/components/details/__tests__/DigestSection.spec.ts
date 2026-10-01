// frontend/src/components/details/__tests__/DigestSection.spec.ts
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import DigestSection from '../DigestSection.vue'
import { jsonResponse, routeFetch } from '../../../test/factories'
import { useDigestStore } from '../../../stores/digest'
import type { SessionDigest } from '../../../types/api'

enableAutoUnmount(afterEach)

const DIGEST: SessionDigest = {
  session_id: 's1', read_at: Math.floor(Date.now() / 1000) - 120, short: 'Executa o plano do agrupador',
  plan_done: false, error: null, error_at: null,
  phases: [
    { title: 'Plano do agrupador', kind: 'plan', status: 'done', done: ['Tarefa 1: tabela'], pending: [], ref: '/p/docs/superpowers/plans/agrupador.md' },
    { title: 'Ajustes no menu', kind: 'adjustments', status: 'open', done: [], pending: ['Ordenar por nome'], ref: null },
  ],
}

let pinia: Pinia
let posts: number

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  posts = 0
})
afterEach(() => vi.unstubAllGlobals())

function stub(digest: SessionDigest | null) {
  vi.stubGlobal('fetch', routeFetch({
    'GET /api/sessions/s1/digest': () => jsonResponse(digest),
    'POST /api/sessions/s1/digest': () => { posts++; return jsonResponse({ queued: true }, 202) },
  }))
}

async function mountSection() {
  const w = mount(DigestSection, { props: { sessionId: 's1' }, global: { plugins: [pinia] } })
  await flushPromises()
  return w
}

describe('seção Resumo', () => {
  it('sem resumo mostra o aviso e o botão', async () => {
    stub(null)
    const w = await mountSection()
    expect(w.find('[data-test="digest-empty"]').text()).toBe('Ainda não resumida')
    expect(w.find('[data-test="digest-request"]').text()).toBe('Resumir agora')
  })

  it('mostra frase, fases, feito, falta e plano ligado', async () => {
    stub(DIGEST)
    const w = await mountSection()
    expect(w.find('[data-test="digest-short"]').text()).toBe('Executa o plano do agrupador')
    const phases = w.findAll('[data-test="digest-phase"]')
    expect(phases).toHaveLength(2)
    expect(phases[0].text()).toContain('Plano')
    expect(phases[0].text()).toContain('Concluída')
    expect(phases[0].text()).toContain('Tarefa 1: tabela')
    expect(phases[0].text()).toContain('agrupador.md')
    expect(phases[1].text()).toContain('Aberta')
    expect(phases[1].text()).toContain('Ordenar por nome')
    expect(w.find('[data-test="digest-read-at"]').text()).toBe('Resumido há 2 min')
    expect(w.find('[data-test="digest-plan-done"]').exists()).toBe(false)
  })

  it('mostra o que falta antes do que foi feito', async () => {
    stub({ ...DIGEST, phases: [{ title: 'Ajustes', kind: 'adjustments', status: 'open', done: ['Feito A'], pending: ['Falta B'], ref: null }] })
    const w = await mountSection()
    const text = w.find('[data-test="digest-phase"]').text()
    expect(text.indexOf('Falta')).toBeGreaterThan(-1)
    expect(text.indexOf('Falta B')).toBeLessThan(text.indexOf('Feito A'))
    expect(text.indexOf('Falta')).toBeLessThan(text.indexOf('Feito'))
  })

  it('cada item de "Feito" tem um marcador discreto e "Falta" mantém o círculo vazio', async () => {
    stub({ ...DIGEST, phases: [{ title: 'Ajustes', kind: 'adjustments', status: 'open', done: ['Feito A', 'Feito B'], pending: ['Falta B'], ref: null }] })
    const w = await mountSection()
    const done = w.findAll('[data-test="digest-done-item"]')
    expect(done).toHaveLength(2)
    for (const item of done) {
      const marker = item.find('[data-test="digest-done-marker"]')
      expect(marker.exists()).toBe(true)
      expect(marker.attributes('aria-hidden')).toBe('true')
      expect(marker.classes()).toContain('bg-fg-subtle')
    }
    expect(w.findAll('[data-test="digest-pending-marker"]')).toHaveLength(1)
  })

  it('mostra o selo de plano concluído', async () => {
    stub({ ...DIGEST, plan_done: true })
    const w = await mountSection()
    expect(w.find('[data-test="digest-plan-done"]').text()).toBe('Plano concluído')
  })

  it('mostra o erro sem esconder o resumo', async () => {
    stub({ ...DIGEST, error: 'O agente demorou demais para responder.' })
    const w = await mountSection()
    expect(w.find('[data-test="digest-error"]').text()).toBe('O agente demorou demais para responder.')
    expect(w.find('[data-test="digest-short"]').exists()).toBe(true)
  })

  it('resumir agora fica em "Resumindo…" até o evento chegar', async () => {
    stub(DIGEST)
    const w = await mountSection()
    await w.find('[data-test="digest-request"]').trigger('click')
    await flushPromises()
    expect(posts).toBe(1)
    const button = w.find('[data-test="digest-request"]')
    expect(button.text()).toBe('Resumindo…')
    expect(button.attributes('disabled')).toBeDefined()
    useDigestStore().applyDigest({ session_id: 's1', digest: { ...DIGEST, short: 'Nova frase' } })
    await flushPromises()
    expect(w.find('[data-test="digest-short"]').text()).toBe('Nova frase')
    expect(w.find('[data-test="digest-request"]').text()).toBe('Resumir agora')
  })

  it('recarrega depois de invalidar', async () => {
    stub(DIGEST)
    await mountSection()
    const calls = () => vi.mocked(fetch).mock.calls.filter(([u]) => u === '/api/sessions/s1/digest').length
    const before = calls()
    useDigestStore().invalidate()
    await flushPromises()
    expect(calls()).toBe(before + 1)
  })

  it('recarrega quando invalidar com a primeira leitura ainda em andamento', async () => {
    let release!: () => void
    const gate = new Promise<void>((r) => { release = r })
    let gets = 0
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/sessions/s1/digest': async () => {
        gets++
        if (gets === 1) { await gate; return jsonResponse({ ...DIGEST, short: 'Primeira' }) }
        return jsonResponse({ ...DIGEST, short: 'Segunda' })
      },
    }))
    const w = mount(DigestSection, { props: { sessionId: 's1' }, global: { plugins: [pinia] } })
    await flushPromises()
    expect(gets).toBe(1)
    useDigestStore().invalidate()
    await flushPromises()
    expect(gets).toBe(2)
    release()
    await flushPromises()
    expect(w.find('[data-test="digest-short"]').text()).toBe('Segunda')
  })
})
