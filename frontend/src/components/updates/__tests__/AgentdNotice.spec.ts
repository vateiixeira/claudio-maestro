import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'

const { applyUpdate, restartAgentd, getUpdates } = vi.hoisted(() => ({ applyUpdate: vi.fn(), restartAgentd: vi.fn(), getUpdates: vi.fn() }))
vi.mock('../../../api/http', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../../api/http')>()),
  applyUpdate, restartAgentd, getUpdates,
}))
import { ApiError } from '../../../api/http'
import AgentdNotice from '../AgentdNotice.vue'
import { useUpdatesStore } from '../../../stores/updates'

enableAutoUnmount(afterEach)
let pinia: Pinia
const RESULT = { from: '0.1.0', to: '0.2.0', agentd_changed: true, at: 1 }
const BASE = { enabled: true, current: '0.2.0', available: false, latest: null, checked_at: null, releases_url: 'r', last_result: RESULT }

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  localStorage.removeItem('maestro:agentd-notice-dismissed')
  getUpdates.mockResolvedValue(BASE as never)
})
afterEach(() => {
  vi.useRealTimers()
  vi.resetAllMocks()
})

const mountIt = () => mount(AgentdNotice, { global: { plugins: [pinia] } })

describe('aviso do agentd', () => {
  it('botão desativado com sessões vivas', () => {
    useUpdatesStore().apply({ ...BASE, agentd: { enabled: true, live_children: 2 } })
    const w = mountIt()
    expect(w.get('[data-test="agentd-notice"]').text()).toContain('O agentd mudou nesta versão')
    expect(w.get('[data-test="agentd-restart"]').attributes('disabled')).toBeDefined()
    expect(w.text()).toContain('2 sessões abertas')
  })

  it('usa o singular com uma sessão', () => {
    useUpdatesStore().apply({ ...BASE, agentd: { enabled: true, live_children: 1 } })
    const text = mountIt().text()
    expect(text).toContain('1 sessão aberta; ela fecha sozinha')
  })

  it('usa o maior entre filhos do agentd e sessões vivas do app', () => {
    useUpdatesStore().apply({ ...BASE, agentd: { enabled: true, live_children: 1 }, live_sessions: 3 })
    const w = mountIt()
    expect(w.text()).toContain('3 sessões abertas')
    expect(w.get('[data-test="agentd-restart"]').attributes('disabled')).toBeDefined()
  })

  it('só sessões vivas no app também bloqueiam, no singular', () => {
    useUpdatesStore().apply({ ...BASE, agentd: { enabled: true, live_children: 0 }, live_sessions: 1 })
    const w = mountIt()
    expect(w.text()).toContain('1 sessão aberta; ela fecha sozinha')
    expect(w.get('[data-test="agentd-restart"]').attributes('disabled')).toBeDefined()
  })

  it('reinicia e some', async () => {
    const spy = restartAgentd.mockResolvedValue({ restarted: true })
    useUpdatesStore().apply({ ...BASE, agentd: { enabled: true, live_children: 0 } })
    const w = mountIt()
    await w.get('[data-test="agentd-restart"]').trigger('click')
    await flushPromises()
    expect(spy).toHaveBeenCalledOnce()
    expect(w.find('[data-test="agentd-notice"]').exists()).toBe(false)
  })

  it('mostra erro do backend', async () => {
    restartAgentd.mockRejectedValue(new ApiError(409, 'há 1 sessão rodando no agentd', 'x'))
    useUpdatesStore().apply({ ...BASE, agentd: { enabled: true, live_children: 0 } })
    const w = mountIt()
    await w.get('[data-test="agentd-restart"]').trigger('click')
    await flushPromises()
    expect(w.get('[data-test="agentd-error"]').text()).toBe('há 1 sessão rodando no agentd')
  })

  it('dispensa sem reiniciar', async () => {
    useUpdatesStore().apply({ ...BASE, agentd: { enabled: true, live_children: 0 } })
    const w = mountIt()
    await w.get('[data-test="agentd-dismiss"]').trigger('click')
    expect(restartAgentd).not.toHaveBeenCalled()
    expect(w.find('[data-test="agentd-notice"]').exists()).toBe(false)
  })

  it('não aparece com agentd desligado', () => {
    useUpdatesStore().apply({ ...BASE, agentd: { enabled: false, live_children: null } })
    expect(mountIt().find('[data-test="agentd-notice"]').exists()).toBe(false)
  })

  it('atualiza a contagem a cada 15 s enquanto visível', async () => {
    vi.useFakeTimers()
    useUpdatesStore().apply({ ...BASE, agentd: { enabled: true, live_children: 1 } })
    const w = mountIt()
    await vi.advanceTimersByTimeAsync(15_000)
    expect(getUpdates).toHaveBeenCalledTimes(1)
    w.unmount()
    await vi.advanceTimersByTimeAsync(30_000)
    expect(getUpdates).toHaveBeenCalledTimes(1)
  })

  it('não consulta enquanto o aviso está oculto', async () => {
    vi.useFakeTimers()
    useUpdatesStore().apply({ ...BASE, agentd: { enabled: false, live_children: null } })
    mountIt()
    await vi.advanceTimersByTimeAsync(30_000)
    expect(getUpdates).not.toHaveBeenCalled()
  })
})
