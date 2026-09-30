import type { DigestPhaseKind, DigestStatus, Effort } from './types/api'

export const MAX_INSTRUCTIONS = 4000

export const DIGEST_LIMITS = {
  interval_minutes: [2, 240],
  min_new_messages: [1, 500],
  open_turn_minutes: [5, 480],
  window_days: [1, 30],
} as const

type NumberField = keyof typeof DIGEST_LIMITS

// Same texts as backend/vibing/digest/config.py MESSAGES.
export const DIGEST_MESSAGES: Record<NumberField | 'model' | 'extra_instructions', string> = {
  model: 'Escolha um modelo da lista.',
  extra_instructions: 'As instruções extras podem ter até 4.000 caracteres.',
  interval_minutes: 'O intervalo precisa ser um número inteiro de 2 a 240 minutos.',
  min_new_messages: 'O mínimo de mensagens novas precisa ser um número inteiro de 1 a 500.',
  open_turn_minutes: 'O teto com turno aberto precisa ser um número inteiro de 5 a 480 minutos.',
  window_days: 'A janela precisa ser um número inteiro de 1 a 30 dias.',
}

export const PHASE_KIND_LABELS: Record<DigestPhaseKind, string> = {
  plan: 'Plano',
  spec: 'Spec',
  feature: 'Feature',
  adjustments: 'Ajustes',
  investigation: 'Investigação',
  other: 'Outro',
}

/** Form values: numbers stay as typed text until saving. */
export interface DigestForm {
  enabled: boolean
  model: string
  effort: Effort
  extra_instructions: string
  interval_minutes: string
  min_new_messages: string
  open_turn_minutes: string
  window_days: string
}

export function digestConfigProblem(form: DigestForm): string | null {
  if (!form.model) return DIGEST_MESSAGES.model
  if (form.extra_instructions.length > MAX_INSTRUCTIONS) return DIGEST_MESSAGES.extra_instructions
  for (const field of Object.keys(DIGEST_LIMITS) as NumberField[]) {
    const raw = String(form[field]).trim()
    const [low, high] = DIGEST_LIMITS[field]
    const value = Number(raw)
    if (!/^\d+$/.test(raw) || value < low || value > high) return DIGEST_MESSAGES[field]
  }
  return null
}

function hhmm(seconds: number): string {
  const date = new Date(seconds * 1000)
  return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
}

export function digestStatusText(status: DigestStatus | null, now: Date = new Date()): string {
  if (!status) return 'Desligado'
  if (status.running) return 'Rodando…'
  if (!status.enabled) return 'Desligado'
  if (status.paused_until && status.paused_until * 1000 > now.getTime()) {
    return `Pausado até ${hhmm(status.paused_until)} (limite da assinatura)`
  }
  if (status.next_run_at) return `Próxima passada às ${hhmm(status.next_run_at)}`
  return 'Ligado'
}
