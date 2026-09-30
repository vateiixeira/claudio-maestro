import { describe, expect, it } from 'vitest'
import { digestConfigProblem, digestStatusText, type DigestForm } from '../digestConfig'

const form = (over: Partial<DigestForm> = {}): DigestForm => ({
  enabled: true, model: 'sonnet', effort: 'medium', extra_instructions: '',
  interval_minutes: '10', min_new_messages: '10', open_turn_minutes: '30', window_days: '3',
  ...over,
})

describe('validação da configuração do agente', () => {
  it('aceita os padrões', () => {
    expect(digestConfigProblem(form())).toBeNull()
  })
  it.each([
    [{ interval_minutes: '1' }, 'O intervalo precisa ser um número inteiro de 2 a 240 minutos.'],
    [{ interval_minutes: '2.5' }, 'O intervalo precisa ser um número inteiro de 2 a 240 minutos.'],
    [{ min_new_messages: '0' }, 'O mínimo de mensagens novas precisa ser um número inteiro de 1 a 500.'],
    [{ open_turn_minutes: '481' }, 'O teto com turno aberto precisa ser um número inteiro de 5 a 480 minutos.'],
    [{ window_days: '' }, 'A janela precisa ser um número inteiro de 1 a 30 dias.'],
    [{ extra_instructions: 'x'.repeat(4001) }, 'As instruções extras podem ter até 4.000 caracteres.'],
    [{ model: '' }, 'Escolha um modelo da lista.'],
  ])('recusa %o', (over, message) => {
    expect(digestConfigProblem(form(over))).toBe(message)
  })
})

describe('texto de estado do agente', () => {
  const now = new Date(2026, 8, 30, 14, 0)
  const at = (h: number, m: number) => Math.floor(new Date(2026, 8, 30, h, m).getTime() / 1000)
  it('desligado, rodando, pausado e próxima passada', () => {
    expect(digestStatusText(null, now)).toBe('Desligado')
    expect(digestStatusText({ enabled: false, running: false, next_run_at: null, paused_until: null }, now)).toBe('Desligado')
    expect(digestStatusText({ enabled: true, running: true, next_run_at: at(14, 10), paused_until: null }, now)).toBe('Rodando…')
    expect(digestStatusText({ enabled: true, running: false, next_run_at: at(14, 10), paused_until: at(18, 0) }, now)).toBe('Pausado até 18:00 (limite da assinatura)')
    expect(digestStatusText({ enabled: true, running: false, next_run_at: at(14, 32), paused_until: null }, now)).toBe('Próxima passada às 14:32')
    expect(digestStatusText({ enabled: false, running: true, next_run_at: null, paused_until: null }, now)).toBe('Rodando…')
  })
})
