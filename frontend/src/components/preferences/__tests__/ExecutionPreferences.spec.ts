import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'

const { applyUpdate, restartAgentd, getUpdates } = vi.hoisted(() => ({ applyUpdate: vi.fn(), restartAgentd: vi.fn(), getUpdates: vi.fn() }))
vi.mock('../../../api/http', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../../api/http')>()),
  applyUpdate, restartAgentd, getUpdates,
}))
import ExecutionPreferences from '../ExecutionPreferences.vue'
import { useUpdatesStore } from '../../../stores/updates'

enableAutoUnmount(afterEach)
let pinia: Pinia
const BASE = { enabled: true, current: '0.1.0', available: false, latest: null, checked_at: null, releases_url: 'r' }

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  getUpdates.mockReturnValue(new Promise(() => {}))
})
afterEach(() => vi.resetAllMocks())

const mountIt = () => mount(ExecutionPreferences, { global: { plugins: [pinia] } })

describe('Preferências → Execução', () => {
  it('terminal: rótulo, aviso e comando', () => {
    useUpdatesStore().apply({ ...BASE, run_mode: { kind: 'terminal', unit: null, kill_mode: null } })
    const w = mountIt()
    expect(w.get('[data-test="execution-mode"]').text()).toBe('Terminal')
    expect(w.find('[data-test="run-mode-notice"]').exists()).toBe(true)
  })

  it('serviço oficial: mostra como remover', () => {
    useUpdatesStore().apply({ ...BASE, run_mode: { kind: 'service-systemd', unit: 'claudio-maestro.service', kill_mode: null } })
    const w = mountIt()
    expect(w.get('[data-test="execution-mode"]').text()).toBe('Serviço oficial (systemd)')
    expect(w.get('[data-test="execution-uninstall"]').text()).toBe('uv run claudio-maestro service uninstall')
  })

  it('sem dados do backend ainda', () => {
    useUpdatesStore().apply(BASE)
    expect(mountIt().text()).toContain('Carregando')
  })

  it('título visível', () => {
    useUpdatesStore().apply({ ...BASE, run_mode: { kind: 'terminal', unit: null, kill_mode: null } })
    expect(mountIt().get('h2').text()).toBe('Execução')
  })

  it('falha ao carregar: mostra o erro e tenta de novo', async () => {
    getUpdates.mockRejectedValueOnce(new Error('fora do ar'))
    const w = mountIt()
    await flushPromises()
    expect(w.text()).not.toContain('Carregando')
    expect(w.get('[role="alert"]').text()).toContain('Não foi possível ler como o Maestro está rodando.')
    getUpdates.mockResolvedValueOnce({ ...BASE, run_mode: { kind: 'terminal', unit: null, kill_mode: null } } as never)
    await w.get('[data-test="execution-retry"]').trigger('click')
    await flushPromises()
    expect(getUpdates).toHaveBeenCalledTimes(2)
    expect(w.get('[data-test="execution-mode"]').text()).toBe('Terminal')
    expect(w.find('[role="alert"]').exists()).toBe(false)
  })
})
