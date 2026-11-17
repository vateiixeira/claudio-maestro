import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'

const socketStatus = await vi.hoisted(async () => ({ value: (await import('vue')).ref('connected') }))
vi.mock('../../../api/socket', () => ({ useEventSocket: () => ({ status: socketStatus.value }) }))

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
  socketStatus.value.value = 'connected'
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

  it('terminal em outra porta: o comando leva a porta', () => {
    useUpdatesStore().apply({ ...BASE, port: 7000, run_mode: { kind: 'terminal', unit: null, kill_mode: null } })
    expect(mountIt().get('[data-test="run-mode-command"]').text()).toBe('uv run claudio-maestro service install --port 7000')
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
    expect(w.get('[data-test="execution-retry"]').classes()).toContain('focus-visible:outline-2')
    getUpdates.mockResolvedValueOnce({ ...BASE, run_mode: { kind: 'terminal', unit: null, kill_mode: null } } as never)
    await w.get('[data-test="execution-retry"]').trigger('click')
    await flushPromises()
    expect(getUpdates).toHaveBeenCalledTimes(2)
    expect(w.get('[data-test="execution-mode"]').text()).toBe('Terminal')
    expect(w.find('[role="alert"]').exists()).toBe(false)
  })

  describe('lista de estado', () => {
    const TERMINAL = { kind: 'terminal', unit: null, kill_mode: null } as const

    it('modo, conexão e versão são linhas de uma lista de definição', () => {
      useUpdatesStore().apply({ ...BASE, run_mode: TERMINAL })
      const w = mountIt()
      const list = w.get('dl')
      for (const test of ['execution-mode', 'execution-connection', 'execution-version']) {
        const dd = w.get(`[data-test="${test}"]`)
        expect(dd.element.tagName).toBe('DD')
        expect(list.element.contains(dd.element)).toBe(true)
      }
      expect(w.findAll('dt').map((d) => d.text())).toEqual(['Como o Maestro está rodando', 'Conexão com o servidor', 'Versão'])
    })

    it('conexão: Conectado', () => {
      useUpdatesStore().apply({ ...BASE, run_mode: TERMINAL })
      expect(mountIt().get('[data-test="execution-connection"]').text()).toBe('Conectado')
    })

    it('conexão: o texto de desconexão do indicador, e volta ao reconectar', async () => {
      useUpdatesStore().apply({ ...BASE, run_mode: TERMINAL })
      socketStatus.value.value = 'reconnecting'
      const w = mountIt()
      expect(w.get('[data-test="execution-connection"]').text()).toBe('Sem conexão com o servidor. Reconectando…')
      socketStatus.value.value = 'connected'
      await flushPromises()
      expect(w.get('[data-test="execution-connection"]').text()).toBe('Conectado')
    })

    it('conexão: ainda conectando, com o ponto neutro', () => {
      useUpdatesStore().apply({ ...BASE, run_mode: TERMINAL })
      socketStatus.value.value = 'connecting'
      const w = mountIt()
      expect(w.get('[data-test="execution-connection"]').text()).toBe('Conectando…')
      const dot = w.get('[data-test="execution-connection"] > span[aria-hidden="true"]')
      expect(dot.classes()).toContain('bg-fg-subtle')
      expect(dot.classes()).not.toContain('bg-primary')
      expect(dot.classes()).not.toContain('bg-secondary')
    })

    it('ponto: verde conectado, laranja reconectando', async () => {
      useUpdatesStore().apply({ ...BASE, run_mode: TERMINAL })
      const w = mountIt()
      const dot = () => w.get('[data-test="execution-connection"] > span[aria-hidden="true"]').classes()
      expect(dot()).toContain('bg-primary')
      socketStatus.value.value = 'reconnecting'
      await flushPromises()
      expect(dot()).toContain('bg-secondary')
    })

    it('versão instalada', () => {
      useUpdatesStore().apply({ ...BASE, current: '0.12.0', run_mode: TERMINAL })
      expect(mountIt().get('[data-test="execution-version"]').text()).toBe('v0.12.0')
    })

    it('serviço próprio: a unidade aparece junto do rótulo', () => {
      useUpdatesStore().apply({ ...BASE, run_mode: { kind: 'systemd', unit: 'claudio-maestro-backend.service', kill_mode: 'process' } })
      const w = mountIt()
      expect(w.get('[data-test="execution-mode"]').text()).toContain('claudio-maestro-backend.service')
      const unit = w.get('[data-test="execution-unit"]')
      expect(unit.text()).toBe('claudio-maestro-backend.service')
      expect(unit.classes()).toContain('font-mono')
      expect(w.get('[data-test="execution-mode"] > span').text()).toBe('Serviço próprio')
      expect(w.get('[data-test="run-mode-notice"]').text()).toContain('Você usa um serviço próprio (claudio-maestro-backend.service).')
    })

    it('serviço oficial: sem aviso nem comando de instalação', () => {
      useUpdatesStore().apply({ ...BASE, run_mode: { kind: 'service-systemd', unit: 'claudio-maestro.service', kill_mode: null } })
      const w = mountIt()
      expect(w.find('[data-test="run-mode-notice"]').exists()).toBe(false)
      expect(w.find('[data-test="execution-copy"]').exists()).toBe(false)
    })

    describe('Copiar', () => {
      let writeText: ReturnType<typeof vi.fn>
      beforeEach(() => {
        writeText = vi.fn().mockResolvedValue(undefined)
        Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
      })

      it('copia o comando mostrado e avisa', async () => {
        useUpdatesStore().apply({ ...BASE, port: 7000, run_mode: TERMINAL })
        const w = mountIt()
        const btn = w.get('[data-test="execution-copy"]')
        expect(btn.text()).toBe('Copiar')
        expect(btn.find('svg[aria-hidden="true"]').exists()).toBe(true)
        await btn.trigger('click')
        await flushPromises()
        expect(writeText).toHaveBeenCalledWith('uv run claudio-maestro service install --port 7000')
        expect(w.get('[data-test="run-mode-command"]').text()).toBe('uv run claudio-maestro service install --port 7000')
        expect(btn.text()).toBe('Copiado')
      })

      it('sem permissão de área de transferência: não quebra e o comando fica visível', async () => {
        writeText.mockRejectedValueOnce(new Error('negado'))
        useUpdatesStore().apply({ ...BASE, run_mode: TERMINAL })
        const w = mountIt()
        await w.get('[data-test="execution-copy"]').trigger('click')
        await flushPromises()
        expect(w.get('[data-test="execution-copy"]').text()).toBe('Copiar')
        expect(w.find('[data-test="run-mode-command"]').exists()).toBe(true)
      })
    })
  })
})
