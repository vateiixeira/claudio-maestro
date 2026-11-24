import type { AgentProvider, Effort, ModelInfo, PermissionMode } from './types/api'

export const PROVIDER_NAMES: Record<AgentProvider, string> = { claude: 'Claude', kimi: 'Kimi Code', codex: 'Codex' }

export const EFFORT_LABELS: Record<Effort, string> = {
  none: 'desativado',
  minimal: 'mínimo',
  low: 'baixo',
  medium: 'médio',
  high: 'alto',
  xhigh: 'muito alto',
  max: 'máximo',
  ultra: 'ultra',
}
export const ALL_EFFORTS: Effort[] = ['low', 'medium', 'high', 'xhigh', 'max']
export const KIMI_EFFORTS: Effort[] = ['low', 'high', 'max']
export const CODEX_EFFORTS = Object.keys(EFFORT_LABELS) as Effort[]

export function codexEffortLevels(model?: ModelInfo): Effort[] {
  return (model?.supportedEffortLevels ?? []).filter((level) => CODEX_EFFORTS.includes(level))
}

export function codexDefaultModel(models: ModelInfo[], configured: string | null = null): ModelInfo | undefined {
  return models.find((model) => model.value === configured) ?? models.find((model) => model.isDefault)
}
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

// Every mode the app offers. "Sem perguntas" is among them: wherever it can be chosen, a confirmation comes first.
export const ALL_MODES = Object.keys(MODE_LABELS) as PermissionMode[]
