import { describe, expect, it } from 'vitest'
import { planBadge, planPosition, planStopped, planVisible } from '../planText'
import type { PlanSummary } from '../../../types/api'

const running: PlanSummary = { path: 'docs/plan.md', title: 'Plano', total: 12, done: 3, current: { number: 4, title: 'Faixa do plano' } }
const complete: PlanSummary = { ...running, done: 12, current: null }

describe('planText', () => {
  it('planPosition mostra a tarefa atual ou "Concluído"', () => {
    expect(planPosition(running)).toBe('Tarefa 4 de 12: Faixa do plano')
    expect(planPosition(complete)).toBe('Concluído')
  })

  it('planBadge mostra tarefa atual/total ou total/total', () => {
    expect(planBadge(running)).toBe('4/12')
    expect(planBadge(complete)).toBe('12/12')
  })

  it('planVisible exige plano em andamento e conversa não finalizada', () => {
    expect(planVisible({ plan: running, finished: false, display_state: 'running' })).toBe(true)
    expect(planVisible({ plan: running, finished: false, display_state: 'waiting' })).toBe(true)
    expect(planVisible({ plan: complete, finished: false, display_state: 'running' })).toBe(false)
    expect(planVisible({ plan: running, finished: true, display_state: 'finished' })).toBe(false)
    expect(planVisible({ plan: running, finished: false, display_state: 'finished' })).toBe(false)
    expect(planVisible({ plan: null, finished: false, display_state: 'running' })).toBe(false)
    expect(planVisible({ finished: false, display_state: 'running' })).toBe(false)
  })

  it('planStopped é verdadeiro quando não está rodando', () => {
    expect(planStopped({ display_state: 'running' })).toBe(false)
    expect(planStopped({ display_state: 'waiting' })).toBe(true)
    expect(planStopped({ display_state: 'finished' })).toBe(true)
  })
})
