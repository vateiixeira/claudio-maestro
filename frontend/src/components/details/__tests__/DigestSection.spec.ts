// frontend/src/components/details/__tests__/DigestSection.spec.ts
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import DigestSection from '../DigestSection.vue'
import { jsonResponse, makeSession, routeFetch } from '../../../test/factories'
import { useDigestStore } from '../../../stores/digest'
import { useSessionsStore } from '../../../stores/sessions'
import { clockNow } from '../../../minuteClock'
import type { SessionDigest } from '../../../types/api'

enableAutoUnmount(afterEach)

// Midday: relative times like "há 2 min" must stay on the same day whatever time the suite runs.
const MIDDAY = new Date(2026, 9, 3, 12, 0, 0)

const DIGEST: SessionDigest = {
  session_id: 's1', read_at: Math.floor(MIDDAY.getTime() / 1000) - 120, short: 'Executa o plano do agrupador',
  plan_done: false, error: null, error_at: null,
  phases: [
    { title: 'Plano do agrupador', kind: 'plan', status: 'done', done: ['Tarefa 1: tabela'], pending: [], ref: '/p/docs/superpowers/plans/agrupador.md' },
    { title: 'Ajustes no menu', kind: 'adjustments', status: 'open', done: [], pending: ['Ordenar por nome'], ref: null },
  ],
}

let pinia: Pinia
let posts: number

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(MIDDAY)
  pinia = createPinia()
  setActivePinia(pinia)
  posts = 0
  // The tests below read the open section; the folded one has its own block.
  localStorage.setItem('maestro:digest-collapsed', 'false')
})
afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
  localStorage.clear()
})

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
    expect(phases[0].text()).toContain('agrupador.md')
    expect(phases[1].text()).toContain('Aberta')
    expect(phases[1].text()).toContain('Ordenar por nome')
    expect(w.find('[data-test="digest-read-at"]').text()).toBe('atualizado há 2 min')
    expect(w.find('[data-test="digest-plan-done"]').exists()).toBe(false)
  })

  it('o "atualizado há…" acompanha o relógio, sem recarregar o resumo', async () => {
    stub(DIGEST)
    const w = await mountSection()
    expect(w.find('[data-test="digest-read-at"]').text()).toBe('atualizado há 2 min')
    vi.setSystemTime(new Date(MIDDAY.getTime() + 3 * 60_000))
    clockNow.value = Date.now()
    await flushPromises()
    expect(w.find('[data-test="digest-read-at"]').text()).toBe('atualizado há 5 min')
  })

  it('a frase curta do resumo vai em texto maior', async () => {
    stub(DIGEST)
    const w = await mountSection()
    expect(w.find('[data-test="digest-short"]').classes()).toContain('text-base')
    expect(w.find('[data-test="digest-short"]').classes()).not.toContain('text-sm')
  })

  it('"Falta" fica à vista, sem clicar, antes dos passos feitos', async () => {
    stub({ ...DIGEST, phases: [{ title: 'Ajustes', kind: 'adjustments', status: 'open', done: ['Feito A'], pending: ['Falta B'], ref: null }] })
    const w = await mountSection()
    expect(w.findAll('[data-test="digest-pending-marker"]')).toHaveLength(1)
    expect(w.find('[data-test="digest-phase"]').text()).toContain('Falta B')
    expect(w.findAll('[data-test="digest-done-item"]')).toHaveLength(0)
    const text = w.find('[data-test="digest-phase"]').text()
    expect(text.indexOf('Falta B')).toBeLessThan(text.indexOf('Ver 1 passo'))
  })

  it('cada item de "Feito" tem um marcador discreto e "Falta" mantém o círculo vazio', async () => {
    stub({ ...DIGEST, phases: [{ title: 'Ajustes', kind: 'adjustments', status: 'open', done: ['Feito A', 'Feito B'], pending: ['Falta B'], ref: null }] })
    const w = await mountSection()
    await w.find('[data-test="digest-steps-toggle"]').trigger('click')
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

  it('o carimbo de atualização fica na linha do título, depois de Resumo', async () => {
    stub(DIGEST)
    const w = await mountSection()
    const row = w.find('[data-test="details-digest"] > div')
    expect(row.text()).toMatch(/^Resumo/)
    expect(row.find('[data-test="digest-read-at"]').exists()).toBe(true)
  })

  it('as fases ficam numa linha do tempo, com nó e rótulo do tipo', async () => {
    stub(DIGEST)
    const w = await mountSection()
    const timeline = w.find('[data-test="digest-timeline"]')
    expect(timeline.exists()).toBe(true)
    const phases = timeline.findAll('[data-test="digest-phase"]')
    expect(phases).toHaveLength(2)
    expect(phases[0].find('[data-test="digest-phase-node"]').attributes('data-status')).toBe('done')
    expect(phases[1].find('[data-test="digest-phase-node"]').attributes('data-status')).toBe('open')
    expect(phases[0].find('[data-test="digest-phase-kind"]').text()).toBe('Plano')
    expect(phases[1].find('[data-test="digest-phase-kind"]').text()).toBe('Ajustes')
    expect(phases[0].find('[data-test="digest-phase-status"]').classes()).toContain('sr-only')
    expect(phases[0].find('[data-test="digest-phase-status"]').text()).toBe('Concluída')
    expect(phases[1].find('[data-test="digest-phase-status"]').text()).toBe('Aberta')
  })

  it('os passos feitos ficam recolhidos e abrem pelo botão', async () => {
    stub({ ...DIGEST, phases: [{ title: 'Plano', kind: 'plan', status: 'done', done: ['A', 'B', 'C', 'D'], pending: [], ref: null }] })
    const w = await mountSection()
    const toggle = () => w.find('[data-test="digest-steps-toggle"]')
    expect(toggle().text()).toBe('Ver os 4 passos')
    expect(toggle().attributes('aria-expanded')).toBe('false')
    expect(w.findAll('[data-test="digest-done-item"]')).toHaveLength(0)
    await toggle().trigger('click')
    expect(w.findAll('[data-test="digest-done-item"]')).toHaveLength(4)
    expect(toggle().text()).toBe('4 passos')
    expect(toggle().attributes('aria-expanded')).toBe('true')
    await toggle().trigger('click')
    expect(w.findAll('[data-test="digest-done-item"]')).toHaveLength(0)
  })

  it('um resumo novo na mesma sessão mantém a expansão na fase, não no índice', async () => {
    const phase = (title: string) => ({ title, kind: 'plan' as const, status: 'done' as const, done: [`passo de ${title}`], pending: [], ref: null })
    stub({ ...DIGEST, phases: [phase('Alfa'), phase('Beta')] })
    const w = await mountSection()
    await w.findAll('[data-test="digest-steps-toggle"]')[0].trigger('click')
    expect(w.findAll('[data-test="digest-done-item"]').map((i) => i.text())).toEqual(['passo de Alfa'])
    useDigestStore().applyDigest({ session_id: 's1', digest: { ...DIGEST, phases: [phase('Nova'), phase('Alfa'), phase('Beta')] } })
    await flushPromises()
    const phases = w.findAll('[data-test="digest-phase"]')
    expect(phases).toHaveLength(3)
    expect(phases[0].find('[data-test="digest-steps-toggle"]').attributes('aria-expanded')).toBe('false')
    expect(phases[1].find('[data-test="digest-steps-toggle"]').attributes('aria-expanded')).toBe('true')
    expect(phases[2].find('[data-test="digest-steps-toggle"]').attributes('aria-expanded')).toBe('false')
    expect(w.findAll('[data-test="digest-done-item"]').map((i) => i.text())).toEqual(['passo de Alfa'])
  })

  it('com um passo feito o botão fica no singular', async () => {
    stub({ ...DIGEST, phases: [{ title: 'Plano', kind: 'plan', status: 'done', done: ['A'], pending: [], ref: null }] })
    const w = await mountSection()
    expect(w.find('[data-test="digest-steps-toggle"]').text()).toBe('Ver 1 passo')
    await w.find('[data-test="digest-steps-toggle"]').trigger('click')
    expect(w.find('[data-test="digest-steps-toggle"]').text()).toBe('1 passo')
  })

  it('sem passos feitos não há botão', async () => {
    stub({ ...DIGEST, phases: [{ title: 'Ajustes', kind: 'adjustments', status: 'open', done: [], pending: ['Falta'], ref: null }] })
    const w = await mountSection()
    expect(w.find('[data-test="digest-steps-toggle"]').exists()).toBe(false)
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

describe('Resumo recolhido', () => {
  beforeEach(() => { localStorage.removeItem('maestro:digest-collapsed') })

  it('começa recolhido: fica a frase curta e o botão, sem a linha do tempo', async () => {
    stub(DIGEST)
    const w = await mountSection()
    const toggle = w.get('[data-test="digest-toggle"]')
    expect(toggle.attributes('aria-expanded')).toBe('false')
    expect(w.get('[data-test="digest-short"]').text()).toBe('Executa o plano do agrupador')
    expect(w.get('[data-test="digest-short"]').classes()).toContain('line-clamp-2')
    expect(w.find('[data-test="digest-timeline"]').exists()).toBe(false)
    expect(w.find('[data-test="digest-request"]').exists()).toBe(true)
    expect(w.find('[data-test="digest-read-at"]').exists()).toBe(true)
  })

  it('o título abre e recolhe a seção e a escolha fica guardada', async () => {
    stub(DIGEST)
    const w = await mountSection()
    const toggle = w.get('[data-test="digest-toggle"]')
    await toggle.trigger('click')
    expect(toggle.attributes('aria-expanded')).toBe('true')
    expect(w.findAll('[data-test="digest-phase"]')).toHaveLength(2)
    expect(w.get('[data-test="digest-short"]').classes()).not.toContain('line-clamp-2')
    expect(localStorage.getItem('maestro:digest-collapsed')).toBe('false')
    await toggle.trigger('click')
    expect(toggle.attributes('aria-expanded')).toBe('false')
    expect(w.find('[data-test="digest-timeline"]').exists()).toBe(false)
    expect(localStorage.getItem('maestro:digest-collapsed')).toBe('true')
  })

  it('abre aberto quando a escolha guardada é aberto', async () => {
    localStorage.setItem('maestro:digest-collapsed', 'false')
    stub(DIGEST)
    const w = await mountSection()
    expect(w.get('[data-test="digest-toggle"]').attributes('aria-expanded')).toBe('true')
    expect(w.findAll('[data-test="digest-phase"]')).toHaveLength(2)
  })

  it('o botão do título controla o corpo da seção e leva o nome Resumo', async () => {
    stub(DIGEST)
    const w = await mountSection()
    const toggle = w.get('[data-test="digest-toggle"]')
    expect(toggle.element.tagName).toBe('BUTTON')
    expect(toggle.text()).toContain('Resumo')
    const body = w.get(`#${toggle.attributes('aria-controls')}`)
    expect(body.attributes('data-test')).toBe('digest-body')
  })

  it('recolhido e sem resumo ainda diz que não foi resumida', async () => {
    stub(null)
    const w = await mountSection()
    expect(w.get('[data-test="digest-empty"]').text()).toBe('Ainda não resumida')
  })

  it('o veredito de fechamento continua à vista com a seção recolhida', async () => {
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/sessions/s1/digest': () => jsonResponse(DIGEST),
      'GET /api/sessions/s1/closure': () => jsonResponse({ session_id: 's1', verdict: 'can_close', user_actions: [], missing: [], evidence: null, checked_at: 5, error: null, error_at: null }),
    }))
    useSessionsStore().setForProject(1, [makeSession({ closure_verdict: 'can_close' })])
    const w = await mountSection()
    expect(w.get('[data-test="digest-toggle"]').attributes('aria-expanded')).toBe('false')
    expect(w.get('[data-test="closure-badge"]').text()).toBe('Pode fechar')
  })

  it('o erro continua à vista com a seção recolhida', async () => {
    stub({ ...DIGEST, error: 'O agente de resumos falhou' })
    const w = await mountSection()
    expect(w.get('[data-test="digest-error"]').text()).toBe('O agente de resumos falhou')
  })
})

describe('bloco Fechamento na seção Resumo', () => {
  const CLOSURE = { session_id: 's1', verdict: 'can_close', user_actions: [], missing: [], evidence: null, checked_at: 5, error: null, error_at: null }

  function stubWithClosure(digest: SessionDigest | null) {
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/sessions/s1/digest': () => jsonResponse(digest),
      'GET /api/sessions/s1/closure': () => jsonResponse(CLOSURE),
    }))
    useSessionsStore().setForProject(1, [makeSession({ closure_verdict: 'can_close' })])
  }

  it('aparece junto do resumo', async () => {
    stubWithClosure(DIGEST)
    const w = await mountSection()
    expect(w.find('[data-test="digest-short"]').exists()).toBe(true)
    expect(w.find('[data-test="closure-badge"]').text()).toBe('Pode fechar')
  })

  it('aparece mesmo sem resumo', async () => {
    stubWithClosure(null)
    const w = await mountSection()
    expect(w.find('[data-test="digest-empty"]').exists()).toBe(true)
    expect(w.find('[data-test="closure-badge"]').text()).toBe('Pode fechar')
  })
})
