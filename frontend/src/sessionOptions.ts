import type { Effort, PermissionMode } from './types/api'

export const EFFORT_LABELS: Record<Effort, string> = {
  low: 'baixo',
  medium: 'médio',
  high: 'alto',
  xhigh: 'muito alto',
  max: 'máximo',
}
export const ALL_EFFORTS = Object.keys(EFFORT_LABELS) as Effort[]
export const MODE_LABELS: Record<PermissionMode, string> = {
  default: 'Pede permissão',
  acceptEdits: 'Aceita edições',
  plan: 'Planejamento',
  bypassPermissions: 'Sem perguntas',
  auto: 'Automático',
  dontAsk: 'Só o pré-aprovado',
}
// A mode the CLI knows but the app does not shows its raw value.
export const modeLabel = (m: string) => MODE_LABELS[m as PermissionMode] ?? m

// Modes offered when starting a conversation: "Sem perguntas" needs a confirmation, only asked inside the conversation.
export const SELECTABLE_MODES: PermissionMode[] = (Object.keys(MODE_LABELS) as PermissionMode[]).filter((m) => m !== 'bypassPermissions')
