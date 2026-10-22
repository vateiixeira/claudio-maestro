import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import ContextBreakdown from '../ContextBreakdown.vue'
import type { ContextBreakdown as Breakdown, ContextDetailsResponse, ContextUsage } from '../../../types/api'

const getSessionContext = vi.hoisted(() => vi.fn())
vi.mock('../../../api/http', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../../api/http')>()),
  getSessionContext,
}))

enableAutoUnmount(afterEach)

const CONTEXT: ContextUsage = { used_tokens: 84800, max_tokens: 400000, percent: 21.2 }

const BREAKDOWN: Breakdown = {
  model: 'claude-opus-5-5',
  total_tokens: 84800,
  max_tokens: 400000,
  percent: 21.2,
  categories: [
    { name: 'Messages', tokens: 35760, kind: 'used' },
    { name: 'MCP tools', tokens: 11600, kind: 'used' },
    { name: 'System prompt', tokens: 7700, kind: 'used' },
    { name: 'Autocompact buffer', tokens: 33000, kind: 'buffer' },
    { name: 'Free space', tokens: 281853, kind: 'free' },
    { name: 'MCP tools (deferred)', tokens: 80300, kind: 'deferred' },
  ],
  mcp_tools: [
    { name: 'smart_search', server: 'claude-mem', tokens: 1900, loaded: true },
    { name: 'batch', server: 'Claude Docs', tokens: 900, loaded: false },
  ],
  memory_files: [],
  agents: [],
  skills: [],
}

const ok = (breakdown: Breakdown = BREAKDOWN): ContextDetailsResponse => ({ available: true, context: CONTEXT, breakdown })
const unavailable = (reason: 'no_process' | 'timeout' | 'failed' | 'unsupported'): ContextDetailsResponse => ({ available: false, reason, context: CONTEXT })

let counter = 0
// The last breakdown per session lives in the module, so every test uses its own session id.
const freshId = () => `ctx-${++counter}`

function mountIt(props: Partial<{ sessionId: string; context: ContextUsage | null; variant: 'popover' | 'panel' }> = {}) {
  return mount(ContextBreakdown, { props: { sessionId: freshId(), context: CONTEXT, variant: 'popover', ...props } })
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}

beforeEach(() => getSessionContext.mockReset())

describe('ContextBreakdown', () => {
  it('mostra cabeçalho, barra e linhas do detalhamento', async () => {
    getSessionContext.mockResolvedValue(ok())
    const w = mountIt()
    await flushPromises()
    expect(w.text()).toContain('21% usado')
    expect(w.text()).toContain('84,8 mil / 400 mil')
    expect(w.findAll('[data-test="ctx-segment"]').length).toBe(4)
    const rows = w.findAll('[data-test="ctx-row"]')
    expect(rows.map((r) => r.text())).toEqual([
      expect.stringContaining('Messages'),
      expect.stringContaining('MCP tools'),
      expect.stringContaining('System prompt'),
      expect.stringContaining('Autocompact buffer'),
      expect.stringContaining('Espaço livre'),
      expect.stringContaining('MCP tools (deferred)'),
    ])
    expect(rows[0].text()).toContain('35,8 mil')
    expect(rows[0].text()).toContain('8,9%')
    expect(rows[5].text()).toContain('—')
    expect(getSessionContext).toHaveBeenCalledTimes(1)
    expect(getSessionContext.mock.calls[0][0]).toMatch(/^ctx-/)
  })

  it('linha com detalhe abre e fecha a sublista', async () => {
    getSessionContext.mockResolvedValue(ok())
    const w = mountIt()
    await flushPromises()
    const toggle = w.find('[data-test="ctx-toggle"]')
    expect(toggle.text()).toContain('MCP tools')
    expect(toggle.attributes('aria-expanded')).toBe('false')
    expect(w.find('[data-test="ctx-details"]').exists()).toBe(false)
    await toggle.trigger('click')
    expect(toggle.attributes('aria-expanded')).toBe('true')
    const details = w.find('[data-test="ctx-details"]')
    expect(details.text()).toContain('claude-mem · smart_search')
    expect(details.text()).toContain('1,9 mil')
    expect(details.text()).not.toContain('Claude Docs')
    await toggle.trigger('click')
    expect(toggle.attributes('aria-expanded')).toBe('false')
    expect(w.find('[data-test="ctx-details"]').exists()).toBe(false)
  })

  it('só as linhas com detalhe viram botão', async () => {
    getSessionContext.mockResolvedValue(ok())
    const w = mountIt()
    await flushPromises()
    // MCP tools and MCP tools (deferred) have details; Messages, System prompt, buffer and free do not.
    expect(w.findAll('[data-test="ctx-toggle"]').map((b) => b.text())).toEqual([
      expect.stringContaining('MCP tools'),
      expect.stringContaining('MCP tools (deferred)'),
    ])
  })

  it.each(['panel', 'popover'] as const)('variant %s começa com as sublistas fechadas', async (variant) => {
    getSessionContext.mockResolvedValue(ok())
    const w = mountIt({ variant })
    await flushPromises()
    expect(w.find('[data-test="ctx-root"]').attributes('data-variant')).toBe(variant)
    expect(w.findAll('[data-test="ctx-toggle"]').every((b) => b.attributes('aria-expanded') === 'false')).toBe(true)
    expect(w.find('[data-test="ctx-details"]').exists()).toBe(false)
  })

  it('no_process mostra o total e a frase da sessão fechada', async () => {
    getSessionContext.mockResolvedValue(unavailable('no_process'))
    const w = mountIt()
    await flushPromises()
    expect(w.text()).toContain('21% usado')
    expect(w.text()).toContain('84,8 mil / 400 mil')
    expect(w.text()).toContain('O detalhamento aparece quando a sessão estiver aberta.')
    expect(w.findAll('[data-test="ctx-row"]').length).toBe(0)
    expect(w.text()).not.toContain('Calculando')
  })

  it.each(['timeout', 'failed', 'unsupported'] as const)('%s mostra a frase de erro', async (reason) => {
    getSessionContext.mockResolvedValue(unavailable(reason))
    const w = mountIt()
    await flushPromises()
    expect(w.text()).toContain('Não foi possível calcular o detalhamento agora.')
  })

  it('falha mantém o detalhamento anterior e mostra a frase de erro', async () => {
    getSessionContext.mockResolvedValueOnce(ok())
    const w = mountIt()
    await flushPromises()
    expect(w.findAll('[data-test="ctx-row"]').length).toBe(6)
    getSessionContext.mockResolvedValueOnce(unavailable('failed'))
    await w.setProps({ context: { ...CONTEXT, used_tokens: 90000 } })
    await flushPromises()
    expect(w.findAll('[data-test="ctx-row"]').length).toBe(6)
    expect(w.text()).toContain('Não foi possível calcular o detalhamento agora.')
  })

  it('erro de rede também mantém o detalhamento e mostra a frase de erro', async () => {
    getSessionContext.mockResolvedValueOnce(ok())
    const w = mountIt()
    await flushPromises()
    getSessionContext.mockRejectedValueOnce(new Error('Failed to fetch'))
    await w.setProps({ context: { ...CONTEXT, used_tokens: 90000 } })
    await flushPromises()
    expect(w.findAll('[data-test="ctx-row"]').length).toBe(6)
    expect(w.text()).toContain('Não foi possível calcular o detalhamento agora.')
  })

  it('a frase de erro some quando uma nova leitura dá certo', async () => {
    getSessionContext.mockResolvedValueOnce(unavailable('timeout'))
    const w = mountIt()
    await flushPromises()
    expect(w.text()).toContain('Não foi possível')
    getSessionContext.mockResolvedValueOnce(ok())
    await w.setProps({ context: { ...CONTEXT, used_tokens: 90000 } })
    await flushPromises()
    expect(w.text()).not.toContain('Não foi possível')
    expect(w.findAll('[data-test="ctx-row"]').length).toBe(6)
  })

  it('busca de novo quando used_tokens muda e não empilha requisições', async () => {
    const first = deferred<ContextDetailsResponse>()
    getSessionContext.mockReturnValueOnce(first.promise)
    const w = mountIt()
    await flushPromises()
    expect(getSessionContext).toHaveBeenCalledTimes(1)

    // Two changes while the first request is still running: a single extra request after it ends.
    await w.setProps({ context: { ...CONTEXT, used_tokens: 85000 } })
    await w.setProps({ context: { ...CONTEXT, used_tokens: 86000 } })
    expect(getSessionContext).toHaveBeenCalledTimes(1)

    getSessionContext.mockResolvedValueOnce(ok())
    first.resolve(ok())
    await flushPromises()
    expect(getSessionContext).toHaveBeenCalledTimes(2)
    await flushPromises()
    expect(getSessionContext).toHaveBeenCalledTimes(2)
  })

  it('não busca de novo quando só o percentual ou outra prop muda sem mudar used_tokens', async () => {
    getSessionContext.mockResolvedValue(ok())
    const w = mountIt()
    await flushPromises()
    await w.setProps({ context: { ...CONTEXT, percent: 22 } })
    await flushPromises()
    expect(getSessionContext).toHaveBeenCalledTimes(1)
  })

  it('descarta a resposta atrasada de outra sessão', async () => {
    const old = deferred<ContextDetailsResponse>()
    const other: Breakdown = { ...BREAKDOWN, categories: [{ name: 'Skills', tokens: 5000, kind: 'used' }], mcp_tools: [] }
    const idA = freshId()
    const idB = freshId()
    getSessionContext.mockReturnValueOnce(old.promise)
    const w = mountIt({ sessionId: idA })
    await flushPromises()

    getSessionContext.mockResolvedValueOnce(ok(other))
    await w.setProps({ sessionId: idB })
    await flushPromises()
    expect(getSessionContext.mock.calls.map((c) => c[0])).toEqual([idA, idB])
    expect(w.findAll('[data-test="ctx-row"]').map((r) => r.text())).toEqual([expect.stringContaining('Skills')])

    old.resolve(ok())
    await flushPromises()
    expect(w.findAll('[data-test="ctx-row"]').map((r) => r.text())).toEqual([expect.stringContaining('Skills')])
    expect(getSessionContext).toHaveBeenCalledTimes(2)
  })

  it('enquanto carrega mostra o total conhecido e "Calculando…"', async () => {
    getSessionContext.mockReturnValueOnce(deferred<ContextDetailsResponse>().promise)
    const w = mountIt()
    await flushPromises()
    expect(w.text()).toContain('21% usado')
    expect(w.text()).toContain('84,8 mil / 400 mil')
    expect(w.text()).toContain('Calculando…')
    expect(w.findAll('[data-test="ctx-row"]').length).toBe(0)
  })

  it('reabrir a mesma sessão mostra na hora o último detalhamento', async () => {
    const id = freshId()
    getSessionContext.mockResolvedValueOnce(ok())
    const first = mountIt({ sessionId: id })
    await flushPromises()
    first.unmount()

    getSessionContext.mockReturnValueOnce(deferred<ContextDetailsResponse>().promise)
    const second = mountIt({ sessionId: id })
    await flushPromises()
    expect(second.findAll('[data-test="ctx-row"]').length).toBe(6)
    expect(second.text()).not.toContain('Calculando…')
    expect(getSessionContext).toHaveBeenCalledTimes(2)
  })

  it('sem contexto conhecido e sem detalhamento mostra só a frase de espera', async () => {
    getSessionContext.mockReturnValueOnce(deferred<ContextDetailsResponse>().promise)
    const w = mountIt({ context: null })
    await flushPromises()
    expect(w.text()).not.toContain('usado')
    expect(w.text()).toContain('Calculando…')
  })

  it('a barra tem descrição para leitor de tela com percentual e tokens', async () => {
    getSessionContext.mockResolvedValue(ok())
    const w = mountIt()
    await flushPromises()
    const bar = w.find('[data-test="ctx-bar"]')
    expect(bar.attributes('role')).toBe('img')
    expect(bar.attributes('aria-label')).toContain('21%')
    expect(bar.attributes('aria-label')).toContain('84,8 mil')
  })
})
