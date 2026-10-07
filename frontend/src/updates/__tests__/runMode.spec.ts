import { describe, expect, it } from 'vitest'
import { runModeLabel, runModeNotice, SERVICE_INSTALL } from '../runMode'

const info = (kind: string, unit: string | null = null, kill_mode: string | null = null) =>
  ({ kind, unit, kill_mode }) as Parameters<typeof runModeNotice>[0]

describe('modo de execução', () => {
  it('rótulos', () => {
    expect(runModeLabel(info('service-systemd'))).toBe('Serviço oficial (systemd)')
    expect(runModeLabel(info('service-launchd'))).toBe('Serviço oficial (launchd)')
    expect(runModeLabel(info('systemd', 'meu.service'))).toBe('Serviço próprio: meu.service')
    expect(runModeLabel(info('launchd', 'com.x'))).toBe('Serviço próprio: com.x')
    expect(runModeLabel(info('terminal'))).toBe('Terminal')
    expect(runModeLabel(info('unknown'))).toBe('Outro')
  })

  it('serviço oficial não tem aviso', () => {
    expect(runModeNotice(info('service-systemd'))).toBeNull()
    expect(runModeNotice(info('service-launchd'))).toBeNull()
  })

  it('terminal avisa que para ao fechar', () => {
    expect(runModeNotice(info('terminal'))).toBe(
      'O Maestro está rodando num terminal: ele reinicia nesse mesmo terminal, não sobe sozinho quando o computador liga e para se o terminal for fechado. Para rodar como serviço:',
    )
  })

  it('serviço próprio menciona a unit e o KillMode', () => {
    const text = runModeNotice(info('systemd', 'meu.service', 'control-group'))!
    expect(text).toContain('Você usa um serviço próprio (meu.service).')
    expect(text).toContain('Com KillMode=control-group, as sessões caem a cada reinício.')
    expect(runModeNotice(info('systemd', 'meu.service', 'process'))).not.toContain('KillMode')
  })

  it('outro modo convida a instalar', () => {
    expect(runModeNotice(info('unknown'))).toBe('Para o Maestro subir sozinho e voltar se cair, rode como serviço:')
  })

  it('comando de instalação', () => {
    expect(SERVICE_INSTALL).toBe('uv run claudio-maestro service install')
  })
})
