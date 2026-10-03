import { MODE_LABELS } from '../sessionOptions'

/** One readable sentence about a permission suggestion: "{lead} {chips}, {scope}". */
export interface RuleDescription {
  lead: string
  /** Rules, modes or folders, shown in monospace. */
  chips: string[]
  /** Where it applies, or null when the suggestion does not say. */
  scope: string | null
}

const SCOPES: Record<string, string> = {
  session: 'só nesta sessão',
  localSettings: 'neste projeto, só para você',
  projectSettings: 'neste projeto, para todos',
  userSettings: 'em todos os seus projetos',
}

const RULE_LEADS: Record<string, string> = {
  allow: 'Libera',
  deny: 'Bloqueia',
  ask: 'Pede confirmação para',
}

// Wording of the action ("Muda o modo para Aceitar edições"), so it differs from the status label.
const MODE_NAMES: Record<string, string> = { ...MODE_LABELS, acceptEdits: 'Aceitar edições' }

const isRecord = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v)

function ruleText(raw: unknown): string | null {
  if (!isRecord(raw) || typeof raw.toolName !== 'string' || !raw.toolName) return null
  const content = typeof raw.ruleContent === 'string' && raw.ruleContent ? raw.ruleContent : null
  return content ? `${raw.toolName}(${content})` : raw.toolName
}

function describeOne(raw: unknown): RuleDescription | null {
  if (!isRecord(raw)) return null
  const scope = typeof raw.destination === 'string' ? (SCOPES[raw.destination] ?? null) : null
  switch (raw.type) {
    case 'addRules':
    case 'replaceRules':
    case 'removeRules': {
      const chips = (Array.isArray(raw.rules) ? raw.rules : []).map(ruleText).filter((t): t is string => t !== null)
      if (chips.length === 0) return null
      const lead = raw.type === 'removeRules' ? 'Remove' : (RULE_LEADS[String(raw.behavior)] ?? RULE_LEADS.allow!)
      return { lead, chips, scope }
    }
    case 'setMode': {
      if (typeof raw.mode !== 'string' || !raw.mode) return null
      return { lead: `Muda o modo para ${MODE_NAMES[raw.mode] ?? raw.mode}`, chips: [], scope }
    }
    case 'addDirectories':
    case 'removeDirectories': {
      const chips = (Array.isArray(raw.directories) ? raw.directories : []).filter((d): d is string => typeof d === 'string' && d !== '')
      if (chips.length === 0) return null
      return { lead: raw.type === 'addDirectories' ? 'Dá acesso a' : 'Tira o acesso a', chips, scope }
    }
    default:
      return null
  }
}

/**
 * Describes the `suggestions` of a permission prompt (the SDK's `PermissionUpdate`, as the backend's
 * `to_dict()` sends them: `type`, `destination`, `rules[{toolName, ruleContent}]`, `behavior`, `mode`,
 * `directories`). Entries it does not understand are left out.
 */
export function describePermissionRule(suggestions: unknown[] | null | undefined): RuleDescription[] {
  return (suggestions ?? []).map(describeOne).filter((d): d is RuleDescription => d !== null)
}
