import { describe, expect, it } from 'vitest'
import { planBadge, planCount, planPosition, planProgressText, planStopped, planVisible } from '../planText'
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

  it('planCount mostra "N de T" da tarefa atual ou "Concluído"', () => {
    const five: PlanSummary = { path: 'docs/plan.md', title: 'Plano', total: 5, done: 2, current: { number: 3, title: 'Terceira' } }
    expect(planCount(five)).toBe('3 de 5')
    expect(planCount({ ...five, done: 5, current: null })).toBe('Concluído')
  })

  it('planProgressText conta concluídas, em andamento e pendentes, no singular quando é 1', () => {
    const base = { path: 'docs/plan.md', title: 'Plano' }
    expect(planProgressText({ ...base, total: 5, done: 2, current: { number: 3, title: 'T' } })).toBe('2 concluídas, 1 em andamento, 2 pendentes')
    expect(planProgressText({ ...base, total: 3, done: 1, current: { number: 2, title: 'T' } })).toBe('1 concluída, 1 em andamento, 1 pendente')
    expect(planProgressText({ ...base, total: 3, done: 3, current: null })).toBe('3 concluídas')
    expect(planProgressText({ ...base, total: 3, done: 0, current: { number: 1, title: 'T' } })).toBe('1 em andamento, 2 pendentes')
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

  it('planStopped considera o CLI rodando como em andamento', () => {
    expect(planStopped({ display_state: 'waiting', cli_running: true })).toBe(false)
    expect(planStopped({ display_state: 'finished', cli_running: true })).toBe(false)
    expect(planStopped({ display_state: 'waiting', cli_running: false })).toBe(true)
    expect(planStopped({ display_state: 'waiting' })).toBe(true)
    expect(planStopped({ display_state: 'running', cli_running: false })).toBe(false)
  })
})
