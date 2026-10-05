import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import type { UsageSnapshot } from '../../../types/api'
import UsageMeter from '../UsageMeter.vue'
import { useUsageStore } from '../../../stores/usage'

enableAutoUnmount(afterEach)

const NOW = new Date(2026, 9, 5, 18, 47).getTime()
const unix = (...args: [number, number, number, number, number]) => new Date(...args).getTime() / 1000

function snapshot(overrides: Partial<UsageSnapshot> = {}): UsageSnapshot {
  return {
    enabled: true,
    limits: [
      { kind: 'session', label: 'Sessão', percent: 14, severity: 'normal', resets_at: unix(2026, 9, 5, 21, 30) },
      { kind: 'weekly_all', label: 'Semana', percent: 87, severity: 'warning', resets_at: unix(2026, 9, 6, 19, 0) },
      { kind: 'weekly_scoped', label: 'Semana · Fable', percent: 3, severity: 'normal', resets_at: unix(2026, 9, 6, 19, 0) },
    ],
    fetched_at: NOW / 1000,
    error: null,
    plan: 'Max 20x',
    ...overrides,
  }
}

function mountWith(data: UsageSnapshot | null) {
  const pinia = createPinia()
  setActivePinia(pinia)
  if (data) useUsageStore().apply(data)
  return mount(UsageMeter, { global: { plugins: [pinia] } })
}

beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(NOW)
})
afterEach(() => vi.useRealTimers())

describe('medidor de consumo', () => {
  it('sem snapshot não mostra nada', () => {
    expect(mountWith(null).find('[data-test="usage-meter"]').exists()).toBe(false)
  })

  it('desligado não mostra nada', () => {
    expect(mountWith(snapshot({ enabled: false, limits: [] })).find('[data-test="usage-meter"]').exists()).toBe(false)
  })

  it('o snapshot inicial, antes da primeira consulta, não mostra faixa vazia', () => {
    const initial = snapshot({ limits: [], plan: null, fetched_at: null, error: null })
    expect(mountWith(initial).find('[data-test="usage-meter"]').exists()).toBe(false)
  })

  it('mostra sessão e semana com percentual, renovação e cor', () => {
    const wrapper = mountWith(snapshot())
    const session = wrapper.get('[data-test="usage-session"]')
    expect(session.text()).toContain('Sessão')
    expect(session.text()).toContain('14%')
    expect(session.text()).toContain('21:30')
    expect(session.get('[data-test="usage-fill"]').classes()).toContain('bg-primary')
    expect(session.get('[data-test="usage-fill"]').attributes('style')).toContain('width: 14%')
    const weekly = wrapper.get('[data-test="usage-weekly_all"]')
    expect(weekly.text()).toContain('ter 19:00')
    expect(weekly.get('[data-test="usage-fill"]').classes()).toContain('bg-secondary')
    expect(wrapper.find('[data-test="usage-weekly_scoped"]').exists()).toBe(false)
  })

  it('a barra é um meter acessível', () => {
    const meter = mountWith(snapshot()).get('[data-test="usage-session"] [role="meter"]')
    expect(meter.attributes('aria-valuenow')).toBe('14')
    expect(meter.attributes('aria-valuemin')).toBe('0')
    expect(meter.attributes('aria-valuemax')).toBe('100')
    expect(meter.attributes('aria-label')).toBe('Sessão: 14%, renova às 21:30')
  })

  it('o tooltip da semana lista os limites por modelo', () => {
    const title = mountWith(snapshot()).get('[data-test="usage-weekly_all"]').attributes('title')
    expect(title).toContain('Renova ter 19:00')
    expect(title).toContain('Fable: 3%')
  })

  it('erro sem números mostra "Uso indisponível" com o motivo no tooltip', () => {
    const wrapper = mountWith(snapshot({ limits: [], fetched_at: null, error: 'Login do CLI expirado' }))
    const line = wrapper.get('[data-test="usage-unavailable"]')
    expect(line.text()).toBe('Uso indisponível')
    expect(line.attributes('title')).toBe('Login do CLI expirado')
  })

  it('erro com números antigos mantém as barras apagadas e explica no tooltip', () => {
    const wrapper = mountWith(snapshot({ error: 'Sem conexão com a Anthropic' }))
    const session = wrapper.get('[data-test="usage-session"]')
    expect(session.classes()).toContain('opacity-60')
    expect(session.attributes('title')).toContain('Não atualizado: Sem conexão com a Anthropic')
    expect(wrapper.find('[data-test="usage-unavailable"]').exists()).toBe(false)
  })

  it('mostra o plano da assinatura no topo, antes das barras', () => {
    const wrapper = mountWith(snapshot())
    const plan = wrapper.get('[data-test="usage-plan"]')
    expect(plan.text()).toContain('Plano')
    expect(plan.text()).toContain('Max 20x')
    expect(plan.attributes('title')).toBe('Plano da assinatura')
    expect(plan.classes()).not.toContain('opacity-60')
    const html = wrapper.html()
    expect(html.indexOf('data-test="usage-plan"')).toBeLessThan(html.indexOf('data-test="usage-session"'))
  })

  it('sem plano a linha não aparece', () => {
    expect(mountWith(snapshot({ plan: null })).find('[data-test="usage-plan"]').exists()).toBe(false)
  })

  it('com erro o plano fica apagado, inclusive junto de "Uso indisponível"', () => {
    expect(mountWith(snapshot({ error: 'Sem conexão com a Anthropic' })).get('[data-test="usage-plan"]').classes()).toContain('opacity-60')
    const unavailable = mountWith(snapshot({ limits: [], fetched_at: null, error: 'Login do CLI expirado' }))
    expect(unavailable.get('[data-test="usage-plan"]').classes()).toContain('opacity-60')
    expect(unavailable.find('[data-test="usage-unavailable"]').exists()).toBe(true)
  })
})
