import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import type { UpdateState } from '../../types/api'

const { applyUpdate, restartAgentd, getUpdates } = vi.hoisted(() => ({ applyUpdate: vi.fn(), restartAgentd: vi.fn(), getUpdates: vi.fn() }))
vi.mock('../../api/http', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/http')>()),
  applyUpdate, restartAgentd, getUpdates,
}))
import { ApiError } from '../../api/http'

import { pageReload, RESTART_TIMEOUT_MS, useUpdatesStore } from '../updates'

function makeState(overrides: Partial<UpdateState> = {}): UpdateState {
  return {
    enabled: true,
    current: '0.1.0',
    available: true,
    latest: { version: '0.2.0', url: 'https://github.com/vateiixeira/claudio-maestro/releases/tag/v0.2.0', notes: '- coisa', published_at: 1791288000 },
    checked_at: 1791303600,
    releases_url: 'https://github.com/vateiixeira/claudio-maestro/releases',
    ...overrides,
  }
}

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.removeItem('maestro:update-dismissed')
  localStorage.removeItem('maestro:update-result-seen')
  localStorage.removeItem('maestro:agentd-notice-dismissed')
})
afterEach(() => {
  vi.restoreAllMocks()
  vi.resetAllMocks()
})

describe('store de versão', () => {
  it('carrega o estado e mostra o aviso quando há versão nova', async () => {
    getUpdates.mockResolvedValue(makeState())
    const store = useUpdatesStore()
    await store.load()
    expect(store.state?.current).toBe('0.1.0')
    expect(store.showNotice).toBe(true)
  })

  it('não mostra o aviso com versão igual, sem release ou desligado', () => {
    const store = useUpdatesStore()
    store.apply(makeState({ available: false }))
    expect(store.showNotice).toBe(false)
    store.apply(makeState({ latest: null, available: false }))
    expect(store.showNotice).toBe(false)
    store.apply(makeState({ enabled: false }))
    expect(store.showNotice).toBe(false)
  })

  it('dispensar esconde só aquela versão e fica guardado', () => {
    const store = useUpdatesStore()
    store.apply(makeState())
    store.openModal()
    store.dismiss()
    expect(store.showNotice).toBe(false)
    expect(store.modalOpen).toBe(false)
    expect(localStorage.getItem('maestro:update-dismissed')).toBe('0.2.0')

    setActivePinia(createPinia())
    const again = useUpdatesStore()
    again.apply(makeState())
    expect(again.showNotice).toBe(false)
    again.apply(makeState({ latest: { ...makeState().latest!, version: '0.3.0' } }))
    expect(again.showNotice).toBe(true)
  })

  it('funciona quando o localStorage lança exceção', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('bloqueado') })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('bloqueado') })
    const store = useUpdatesStore()
    store.apply(makeState())
    expect(store.showNotice).toBe(true)
    store.dismiss()
    expect(store.showNotice).toBe(false)
  })

  it('o evento app.update troca o estado e ignora dados inválidos', () => {
    const store = useUpdatesStore()
    store.apply(makeState())
    store.apply({ nada: 1 })
    store.apply(null)
    expect(store.state?.latest?.version).toBe('0.2.0')
  })

  it('ignora resposta do load que chegou depois de um evento', async () => {
    let resolve!: (value: UpdateState) => void
    getUpdates.mockReturnValue(new Promise<UpdateState>((r) => { resolve = r }))
    const store = useUpdatesStore()
    const pending = store.load()
    store.apply(makeState({ latest: { ...makeState().latest!, version: '0.3.0' } }))
    resolve(makeState())
    await pending
    expect(store.state?.latest?.version).toBe('0.3.0')
  })

  it('openModal só abre quando há release', () => {
    const store = useUpdatesStore()
    store.openModal()
    expect(store.modalOpen).toBe(false)
    store.apply(makeState())
    store.openModal()
    expect(store.modalOpen).toBe(true)
    store.closeModal()
    expect(store.modalOpen).toBe(false)
  })
})

const BASE = {
  enabled: true, current: '0.1.0', available: true,
  latest: { version: '0.2.0', url: 'u', notes: '', published_at: null },
  checked_at: 1, releases_url: 'r',
}
const JOB = { state: 'running', step: 'fetch', rolling_back: false, lines: ['a'], error: null, log_path: '/d/update.log' }

describe('atualização pelo app', () => {
  it('evento app.update mescla em vez de apagar os campos do GET', () => {
    const store = useUpdatesStore()
    store.apply({ ...BASE, run_mode: { kind: 'terminal', unit: null, kill_mode: null } })
    store.apply({ ...BASE, checked_at: 2 })
    expect(store.state?.run_mode?.kind).toBe('terminal')
    expect(store.state?.checked_at).toBe(2)
  })

  it('progresso entra no job', () => {
    const store = useUpdatesStore()
    store.apply(BASE)
    store.applyProgress(JOB)
    expect(store.state?.job?.step).toBe('fetch')
    store.applyProgress({ bobagem: true })
    expect(store.state?.job?.step).toBe('fetch')
  })

  it('recarrega a página quando a versão muda', () => {
    const reload = vi.spyOn(pageReload, 'reload').mockImplementation(() => {})
    const store = useUpdatesStore()
    store.apply(BASE)
    store.apply({ ...BASE, current: '0.1.0' })
    expect(reload).not.toHaveBeenCalled()
    store.apply({ ...BASE, current: '0.2.0' })
    expect(reload).toHaveBeenCalledOnce()
  })

  it('marca demora quando o app não volta em 60 s', () => {
    vi.useFakeTimers()
    try {
      const store = useUpdatesStore()
      store.apply(BASE)
      store.applyProgress({ ...JOB, state: 'restarting', step: 'restart' })
      vi.advanceTimersByTime(RESTART_TIMEOUT_MS - 1)
      expect(store.restartTimedOut).toBe(false)
      vi.advanceTimersByTime(1)
      expect(store.restartTimedOut).toBe(true)
    } finally {
      vi.useRealTimers()
    }
  })

  it('startUpdate chama a API com a versão anunciada e guarda o erro', async () => {
    const spy = applyUpdate.mockRejectedValueOnce(new ApiError(409, 'há arquivos alterados no clone', 'x'))
    const store = useUpdatesStore()
    store.apply(BASE)
    await store.startUpdate()
    expect(spy).toHaveBeenCalledWith('0.2.0', false)
    expect(store.applyError).toBe('há arquivos alterados no clone')
  })

  it('409 de sessões liga a confirmação com o número do backend, sem erro', async () => {
    const detail = { code: 'sessions_drop', sessions: 3, message: '3 sessões em andamento serão encerradas; confirme para continuar' }
    applyUpdate.mockRejectedValueOnce(new ApiError(409, detail.message, 'x', detail))
    const store = useUpdatesStore()
    store.apply(BASE)
    await store.startUpdate()
    expect(store.confirmSessions).toBe(3)
    expect(store.applyError).toBeNull()
    expect(store.applying).toBe(false)
  })

  it('outros 409 continuam como erro de texto', async () => {
    applyUpdate.mockRejectedValueOnce(new ApiError(409, 'já há uma atualização em andamento', 'x'))
    const store = useUpdatesStore()
    store.apply(BASE)
    await store.startUpdate()
    expect(store.confirmSessions).toBeNull()
    expect(store.applyError).toBe('já há uma atualização em andamento')
  })

  it('confirmar chama de novo com a confirmação e limpa o pedido', async () => {
    const detail = { code: 'sessions_drop', sessions: 1, message: 'm' }
    applyUpdate.mockRejectedValueOnce(new ApiError(409, 'm', 'x', detail))
    applyUpdate.mockResolvedValueOnce({ job: JOB })
    const store = useUpdatesStore()
    store.apply(BASE)
    await store.startUpdate()
    await store.startUpdate(true)
    expect(applyUpdate).toHaveBeenLastCalledWith('0.2.0', true)
    expect(store.confirmSessions).toBeNull()
  })

  it('fechar o modal esquece o pedido de confirmação', async () => {
    applyUpdate.mockRejectedValueOnce(new ApiError(409, 'm', 'x', { code: 'sessions_drop', sessions: 1, message: 'm' }))
    const store = useUpdatesStore()
    store.apply(BASE)
    await store.startUpdate()
    store.closeModal()
    expect(store.confirmSessions).toBeNull()
  })

  it('GET atrasado não troca o job que um evento de progresso já atualizou, mas mescla o resto', async () => {
    let resolve!: (value: UpdateState) => void
    getUpdates.mockReturnValue(new Promise<UpdateState>((r) => { resolve = r }))
    const store = useUpdatesStore()
    store.apply(BASE)
    const pending = store.load()
    store.applyProgress({ ...JOB, state: 'restarting', step: 'restart' })
    resolve({ ...BASE, job: JOB as never, live_sessions: 4 })
    await pending
    expect(store.state?.job?.state).toBe('restarting')
    expect(store.state?.live_sessions).toBe(4)
  })

  it('GET sem evento no meio troca o job normalmente', async () => {
    getUpdates.mockResolvedValue({ ...BASE, job: JOB as never })
    const store = useUpdatesStore()
    store.apply(BASE)
    await store.load()
    expect(store.state?.job?.step).toBe('fetch')
  })

  it('a resposta do POST não troca o job quando um evento de progresso chegou antes', async () => {
    let resolve!: (value: { job: typeof JOB }) => void
    applyUpdate.mockReturnValue(new Promise((r) => { resolve = r }))
    const store = useUpdatesStore()
    store.apply(BASE)
    const pending = store.startUpdate()
    store.applyProgress({ ...JOB, state: 'restarting', step: 'restart' })
    resolve({ job: JOB })
    await pending
    expect(store.state?.job?.state).toBe('restarting')
  })

  it('a resposta do POST entra quando nenhum evento chegou, mesmo sobre um job final antigo', async () => {
    applyUpdate.mockResolvedValue({ job: JOB })
    const store = useUpdatesStore()
    store.apply({ ...BASE, job: { ...JOB, state: 'failed' } as never })
    await store.startUpdate()
    expect(store.state?.job?.state).toBe('running')
  })

  it('aviso de atualizado aparece uma vez por versão', () => {
    const store = useUpdatesStore()
    store.apply({ ...BASE, last_result: { from: '0.1.0', to: '0.2.0', agentd_changed: false, at: 1 } })
    expect(store.showUpdatedNotice).toBe(true)
    store.dismissUpdatedNotice()
    expect(store.showUpdatedNotice).toBe(false)
    expect(localStorage.getItem('maestro:update-result-seen')).toBe('0.2.0')
  })

  it('aviso do agentd só com agentd ligado e mudança na versão', () => {
    const store = useUpdatesStore()
    store.apply({ ...BASE, last_result: { from: '0.1.0', to: '0.2.0', agentd_changed: true, at: 1 }, agentd: { enabled: true, live_children: 2 } })
    expect(store.showAgentdNotice).toBe(true)
    expect(store.agentdBusy).toBe(true)
    store.dismissAgentdNotice()
    expect(store.showAgentdNotice).toBe(false)
  })

  it('agentd ocupado com filhos vivos ou sessões vivas no app', () => {
    const store = useUpdatesStore()
    const result = { from: '0.1.0', to: '0.2.0', agentd_changed: true, at: 1 }
    store.apply({ ...BASE, last_result: result, agentd: { enabled: true, live_children: 0 }, live_sessions: 0 })
    expect(store.agentdBusy).toBe(false)
    store.apply({ ...BASE, last_result: result, agentd: { enabled: true, live_children: 0 }, live_sessions: 1 })
    expect(store.agentdBusy).toBe(true)
    store.apply({ ...BASE, last_result: result, agentd: { enabled: true, live_children: null }, live_sessions: 0 })
    expect(store.agentdBusy).toBe(false)
  })
})
