import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { nextTick } from 'vue'
import UpdateModal from '../UpdateModal.vue'
import { useUpdatesStore } from '../../../stores/updates'

const { applyUpdate, restartAgentd, getUpdates } = vi.hoisted(() => ({ applyUpdate: vi.fn(), restartAgentd: vi.fn(), getUpdates: vi.fn() }))
vi.mock('../../../api/http', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../../api/http')>()),
  applyUpdate, restartAgentd, getUpdates,
}))
import { ApiError } from '../../../api/http'

afterEach(() => vi.resetAllMocks())

enableAutoUnmount(afterEach)
let pinia: Pinia
const RELEASES = 'https://github.com/vateiixeira/claudio-maestro/releases'

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  localStorage.removeItem('maestro:update-dismissed')
  useUpdatesStore().apply({
    enabled: true,
    current: '0.1.0',
    available: true,
    latest: { version: '0.2.0', url: `${RELEASES}/tag/v0.2.0`, notes: '### Adicionado\n- Aviso de versão', published_at: 1791288000 },
    checked_at: 1791303600,
    releases_url: RELEASES,
    run_mode: { kind: 'terminal', unit: null, kill_mode: null },
    self_update: { can: false, reason: null, mode: null },
    job: null,
    agentd: { enabled: true, live_children: 0 },
    live_sessions: 0,
  })
  useUpdatesStore().openModal()
})

function mountModal() {
  return mount(UpdateModal, { attachTo: document.body, global: { plugins: [pinia] } })
}

describe('modal de versão nova', () => {
  it('mostra versões, notas e os comandos', () => {
    const wrapper = mountModal()
    expect(wrapper.get('[role="dialog"]').attributes('aria-modal')).toBe('true')
    expect(wrapper.text()).toContain('Versão 0.2.0 disponível')
    expect(wrapper.text()).toContain('Você está na 0.1.0')
    expect(wrapper.get('[data-test="update-notes"] h3').text()).toBe('Adicionado')
    expect(wrapper.get('[data-test="update-commands"]').text()).toContain('git pull')
    expect(wrapper.get('[data-test="update-github"]').attributes('href')).toBe(`${RELEASES}/tag/v0.2.0`)
  })

  it('renderiza HTML das notas como texto', () => {
    const updates = useUpdatesStore()
    updates.apply({ ...updates.state!, latest: { ...updates.state!.latest!, notes: '<script>alert(1)</script><img src=x onerror=alert(1)>' } })
    const wrapper = mountModal()
    const notes = wrapper.get('[data-test="update-notes"]')
    expect(notes.find('script').exists()).toBe(false)
    expect(notes.find('img').exists()).toBe(false)
    expect(notes.text()).toContain('<script>')
  })

  it('Dispensar grava a versão e fecha', async () => {
    const wrapper = mountModal()
    await wrapper.get('[data-test="update-dismiss"]').trigger('click')
    const updates = useUpdatesStore()
    expect(updates.modalOpen).toBe(false)
    expect(updates.showNotice).toBe(false)
    expect(localStorage.getItem('maestro:update-dismissed')).toBe('0.2.0')
  })

  it('Esc e Fechar fecham sem dispensar', async () => {
    const wrapper = mountModal()
    await wrapper.get('[role="dialog"]').trigger('keydown', { key: 'Escape' })
    const updates = useUpdatesStore()
    expect(updates.modalOpen).toBe(false)
    expect(updates.showNotice).toBe(true)
  })

  it('devolve o foco para quem abriu', async () => {
    const opener = document.createElement('button')
    document.body.appendChild(opener)
    opener.focus()
    const wrapper = mountModal()
    await nextTick()
    await nextTick()
    expect(document.activeElement).toBe(wrapper.get('[data-test="update-close"]').element)
    await wrapper.get('[data-test="update-close"]').trigger('click')
    wrapper.unmount()
    expect(document.activeElement).toBe(opener)
    opener.remove()
  })
})

const CAN = { can: true, reason: null, mode: 'pull' as const }
const job = (over: Partial<Record<string, unknown>> = {}) => ({
  state: 'running', step: 'python', rolling_back: false, lines: ['Resolved 80 packages'], error: null, log_path: '/d/update.log', ...over,
})

function setState(extra: Record<string, unknown>) {
  const store = useUpdatesStore()
  store.apply({ ...store.state!, ...extra })
}

describe('atualizar pelo app', () => {
  it('mostra o botão e o aviso do terminal quando pode atualizar', () => {
    setState({ self_update: CAN, run_mode: { kind: 'terminal', unit: null, kill_mode: null } })
    const w = mountModal()
    expect(w.get('[data-test="update-apply"]').text()).toBe('Atualizar agora')
    expect(w.get('[data-test="run-mode-notice"]').text()).toContain('rodando num terminal')
    expect(w.get('[data-test="update-manual"]').element.tagName).toBe('DETAILS')
  })

  it('sem poder atualizar, explica e mostra os comandos abertos', () => {
    setState({ self_update: { can: false, reason: 'há arquivos alterados no clone', mode: null } })
    const w = mountModal()
    expect(w.find('[data-test="update-apply"]').exists()).toBe(false)
    expect(w.get('[data-test="update-unavailable"]').text()).toBe('Atualização automática indisponível: há arquivos alterados no clone.')
    expect(w.get('[data-test="update-commands"]').text()).toContain('git pull')
  })

  it('no modo tag, os comandos manuais são de tag', () => {
    setState({ self_update: { can: false, reason: 'x', mode: 'tag' } })
    expect(mountModal().get('[data-test="update-commands"]').text()).toContain('git checkout --detach v0.2.0')
  })

  it('clicar chama a atualização', async () => {
    const spy = applyUpdate.mockResolvedValue({ job: job() as never })
    setState({ self_update: CAN })
    const w = mountModal()
    await w.get('[data-test="update-apply"]').trigger('click')
    expect(spy).toHaveBeenCalledWith('0.2.0', false)
  })

  it('sem agentd e com sessões vivas, pede confirmação', async () => {
    const spy = applyUpdate.mockResolvedValue({ job: null })
    setState({ self_update: CAN, agentd: { enabled: false, live_children: null }, live_sessions: 2 })
    const w = mountModal()
    await w.get('[data-test="update-apply"]').trigger('click')
    expect(spy).not.toHaveBeenCalled()
    expect(w.text()).toContain('2 sessões em andamento serão encerradas')
    await w.get('[data-test="update-confirm-drop"]').trigger('click')
    expect(spy).toHaveBeenCalledWith('0.2.0', true)
  })

  it('com uma sessão, usa o singular', async () => {
    setState({ self_update: CAN, agentd: { enabled: false, live_children: null }, live_sessions: 1 })
    const w = mountModal()
    await w.get('[data-test="update-apply"]').trigger('click')
    expect(w.text()).toContain('1 sessão em andamento será encerrada.')
  })

  it('mostra os passos e a saída durante a atualização', () => {
    setState({ self_update: CAN, job: job() })
    const w = mountModal()
    expect(w.get('[data-test="update-step-fetch"]').attributes('data-status')).toBe('done')
    expect(w.get('[data-test="update-step-python"]').attributes('data-status')).toBe('running')
    expect(w.get('[data-test="update-step-build"]').attributes('data-status')).toBe('pending')
    expect(w.get('[data-test="update-output"]').text()).toContain('Resolved 80 packages')
    expect(w.find('[data-test="update-apply"]').exists()).toBe(false)
  })

  it('não fecha com Esc enquanto atualiza, mas o X fecha', async () => {
    setState({ self_update: CAN, job: job() })
    const w = mountModal()
    await w.get('[role="dialog"]').trigger('keydown', { key: 'Escape' })
    expect(useUpdatesStore().modalOpen).toBe(true)
    await w.get('[data-test="update-close"]').trigger('click')
    expect(useUpdatesStore().modalOpen).toBe(false)
  })

  it('falha desfeita mostra erro, log e comandos', () => {
    setState({ self_update: CAN, job: job({ state: 'failed', step: 'build', error: '`pnpm build` falhou (código 1)' }) })
    const w = mountModal()
    const failed = w.get('[data-test="update-failed"]').text()
    expect(failed).toContain('`pnpm build` falhou (código 1)')
    expect(failed).toContain('A atualização foi desfeita')
    expect(failed).toContain('/d/update.log')
    expect(w.get('[data-test="update-step-build"]').attributes('data-status')).toBe('failed')
    expect(w.get('[data-test="update-commands"]').text()).toContain('git pull')
    expect(w.find('[data-test="update-apply"]').exists()).toBe(true)
  })

  it('falha sem desfazer avisa', () => {
    setState({ self_update: CAN, job: job({ state: 'rolled-back-failed', error: 'x. Não foi possível desfazer: y' }) })
    expect(mountModal().get('[data-test="update-failed"]').text()).toContain('Não foi possível desfazer')
  })

  it('reiniciando e demora', async () => {
    vi.useFakeTimers()
    try {
      setState({ self_update: CAN, job: job({ state: 'restarting', step: 'restart' }) })
      const w = mountModal()
      expect(w.get('[data-test="update-restarting"]').text()).toContain('Reiniciando')
      vi.advanceTimersByTime(60_000)
      await nextTick()
      expect(w.get('[data-test="update-timeout"]').text()).toContain('/d/update.log')
    } finally {
      vi.useRealTimers()
    }
  })

  it('já está na versão mais nova', () => {
    setState({ self_update: CAN, job: job({ state: 'up-to-date', step: 'fetch' }) })
    expect(mountModal().text()).toContain('O clone já está na versão mais nova')
  })

  it('mostra erro ao iniciar', async () => {
    applyUpdate.mockRejectedValue(new ApiError(409, 'já há uma atualização em andamento', 'x'))
    setState({ self_update: CAN })
    const w = mountModal()
    await w.get('[data-test="update-apply"]').trigger('click')
    await nextTick()
    expect(w.get('[data-test="update-apply-error"]').text()).toBe('já há uma atualização em andamento')
  })

  it('depois do clique que inicia, o foco vai para o X', async () => {
    applyUpdate.mockResolvedValue({ job: job() as never })
    setState({ self_update: CAN })
    const w = mountModal()
    await w.get('[data-test="update-apply"]').trigger('click')
    await flushPromises()
    await nextTick()
    expect(w.find('[data-test="update-apply"]').exists()).toBe(false)
    expect(document.activeElement).toBe(w.get('[data-test="update-close"]').element)
  })

  it('depois do clique que pede confirmação, o foco vai para o botão de confirmar', async () => {
    setState({ self_update: CAN, agentd: { enabled: false, live_children: null }, live_sessions: 2 })
    const w = mountModal()
    await w.get('[data-test="update-apply"]').trigger('click')
    await flushPromises()
    await nextTick()
    expect(document.activeElement).toBe(w.get('[data-test="update-confirm-drop"]').element)
  })

  it('Dispensar fica desabilitado enquanto atualiza', () => {
    setState({ self_update: CAN, job: job() })
    expect(mountModal().get('[data-test="update-dismiss"]').attributes('disabled')).toBeDefined()
  })

  it('clique fora não fecha enquanto atualiza', async () => {
    setState({ self_update: CAN, job: job() })
    const w = mountModal()
    await w.get('[role="dialog"]').element.parentElement!.click()
    expect(useUpdatesStore().modalOpen).toBe(true)
  })

  it('clique fora fecha quando não há atualização em andamento', async () => {
    const w = mountModal()
    await w.get('[role="dialog"]').element.parentElement!.click()
    expect(useUpdatesStore().modalOpen).toBe(false)
  })

  it('mostra "Desfazendo…" ao desfazer', () => {
    setState({ self_update: CAN, job: job({ state: 'running', step: 'build', rolling_back: true }) })
    expect(mountModal().get('[data-test="update-steps"]').element.parentElement!.textContent).toContain('Desfazendo…')
  })
})
