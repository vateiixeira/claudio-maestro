import type { RunModeInfo } from '../types/api'

const DEFAULT_PORT = 6660

/** The install command; it carries the app's port when that is not the default, so the service listens where the app does now. */
export function serviceInstallCommand(port?: number): string {
  const base = 'uv run claudio-maestro service install'
  return port === undefined || port === DEFAULT_PORT ? base : `${base} --port ${port}`
}
export const SERVICE_UNINSTALL = 'uv run claudio-maestro service uninstall'

export function runModeLabel(info: RunModeInfo): string {
  switch (info.kind) {
    case 'service-systemd': return 'Serviço oficial (systemd)'
    case 'service-launchd': return 'Serviço oficial (launchd)'
    case 'systemd':
    case 'launchd': return `Serviço próprio: ${info.unit ?? 'desconhecido'}`
    case 'terminal': return 'Terminal'
    default: return 'Outro'
  }
}

/** The warning for this way of running, ending where the install command follows; null for the official service. */
export function runModeNotice(info: RunModeInfo): string | null {
  switch (info.kind) {
    case 'service-systemd':
    case 'service-launchd':
      return null
    case 'systemd':
    case 'launchd': {
      const killMode = info.kill_mode === 'control-group' ? ' Com KillMode=control-group, as sessões caem a cada reinício.' : ''
      return `Você usa um serviço próprio (${info.unit ?? 'desconhecido'}).${killMode} O oficial já vem configurado para as sessões sobreviverem ao reinício:`
    }
    case 'terminal':
      return 'O Maestro está rodando num terminal: ele reinicia nesse mesmo terminal, não sobe sozinho quando o computador liga e para se o terminal for fechado. Para rodar como serviço:'
    default:
      return 'Para o Maestro subir sozinho e voltar se cair, rode como serviço:'
  }
}
