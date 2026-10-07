import { afterEach, describe, expect, it } from 'vitest'
import { enableAutoUnmount, mount } from '@vue/test-utils'
import RunModeNotice from '../RunModeNotice.vue'

enableAutoUnmount(afterEach)

describe('RunModeNotice', () => {
  it('mostra aviso e comando no terminal', () => {
    const w = mount(RunModeNotice, { props: { runMode: { kind: 'terminal', unit: null, kill_mode: null } } })
    expect(w.get('[data-test="run-mode-notice"]').text()).toContain('rodando num terminal')
    expect(w.get('[data-test="run-mode-command"]').text()).toBe('uv run claudio-maestro service install')
  })

  it('não renderiza nada no serviço oficial', () => {
    const w = mount(RunModeNotice, { props: { runMode: { kind: 'service-systemd', unit: 'claudio-maestro.service', kill_mode: null } } })
    expect(w.find('[data-test="run-mode-notice"]').exists()).toBe(false)
  })
})
