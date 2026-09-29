import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { jsonResponse, routeFetch } from '../../../test/factories'
import SubagentStrip from '../SubagentStrip.vue'
import type { SubagentEntry } from '../../../conversation/subagents'

const entry = (id: string, status: SubagentEntry['status'], extra: Partial<SubagentEntry> = {}): SubagentEntry => ({
  id, kind: 'reviewer', description: `desc ${id}`, status, lastAction: `Read ${id}.py`, ...extra,
})
const rows = (w: ReturnType<typeof mount>) => w.findAll('[data-test="subagent-row"]')

describe('faixa de subagentes', () => {
  it('não renderiza nada sem subagentes', () => {
    const w = mount(SubagentStrip, { props: { sessionId: 's1', entries: [] } })
    expect(w.find('[data-test="subagent-strip"]').exists()).toBe(false)
  })

  it('até 3 mostra a lista direto, com tipo, descrição, estado e última ação', () => {
    const w = mount(SubagentStrip, { props: { sessionId: 's1', entries: [entry('a', 'running'), entry('b', 'completed'), entry('c', 'failed')] } })
    expect(w.find('[data-test="subagent-summary"]').exists()).toBe(false)
    expect(rows(w)).toHaveLength(3)
    const first = rows(w)[0]!
    expect(first.text()).toContain('reviewer')
    expect(first.text()).toContain('desc a')
    expect(first.text()).toContain('Read a.py')
    expect(first.find('[data-status="running"]').attributes('aria-label')).toBe('Rodando')
    expect(rows(w)[1]!.find('[data-status="completed"]').attributes('aria-label')).toBe('Concluído')
    expect(rows(w)[2]!.find('[data-status="failed"]').attributes('aria-label')).toBe('Com erro')
  })

  it('estado parado tem rótulo próprio', () => {
    const w = mount(SubagentStrip, { props: { sessionId: 's1', entries: [entry('a', 'running'), entry('b', 'stopped')] } })
    expect(rows(w)[1]!.find('[data-status="stopped"]').attributes('aria-label')).toBe('Parado')
  })

  it('clicar na linha pede para ir ao cartão', async () => {
    const w = mount(SubagentStrip, { props: { sessionId: 's1', entries: [entry('a', 'running'), entry('b', 'completed')] } })
    await rows(w)[1]!.trigger('click')
    expect(w.emitted('select')).toEqual([['b']])
  })

  it('mais de 3 mostra o resumo recolhido; clicar abre a lista e de novo recolhe', async () => {
    const entries = [entry('a', 'running'), entry('b', 'running'), entry('c', 'running'), entry('d', 'completed')]
    const w = mount(SubagentStrip, { props: { sessionId: 's1', entries } })
    const summary = w.find('[data-test="subagent-summary"]')
    expect(summary.text()).toContain('3 rodando, 1 concluído')
    expect(summary.element.tagName).toBe('BUTTON')
    expect(summary.attributes('aria-expanded')).toBe('false')
    expect(rows(w)).toHaveLength(0)
    await summary.trigger('click')
    expect(summary.attributes('aria-expanded')).toBe('true')
    expect(rows(w)).toHaveLength(4)
    await summary.trigger('click')
    expect(rows(w)).toHaveLength(0)
  })

  it('linhas são botões alcançáveis pelo teclado', () => {
    const w = mount(SubagentStrip, { props: { sessionId: 's1', entries: [entry('a', 'running')] } })
    const row = rows(w)[0]!
    expect(row.element.tagName).toBe('BUTTON')
    expect(row.attributes('type')).toBe('button')
  })

  it('região nomeada para leitores de tela', () => {
    const w = mount(SubagentStrip, { props: { sessionId: 's1', entries: [entry('a', 'running')] } })
    const region = w.find('[data-test="subagent-strip"]')
    expect(region.attributes('role')).toBe('region')
    expect(region.attributes('aria-label')).toBe('Subagentes')
  })

  it('sem última ação não deixa linha vazia', () => {
    const w = mount(SubagentStrip, { props: { sessionId: 's1', entries: [entry('a', 'running', { lastAction: '' })] } })
    expect(w.find('[data-test="subagent-last-action"]').exists()).toBe(false)
  })

  describe('parar subagentes', () => {
    afterEach(() => vi.unstubAllGlobals())
    const stop = (w: ReturnType<typeof mount>) => w.find('[data-test="subagent-stop"]')

    it('aparece enquanto algum roda, sem depender do estado da sessão', () => {
      const w = mount(SubagentStrip, { props: { sessionId: 's1', entries: [entry('a', 'running'), entry('b', 'running')] } })
      const button = stop(w)
      expect(button.exists()).toBe(true)
      expect(button.element.tagName).toBe('BUTTON')
      expect(button.attributes('type')).toBe('button')
      expect(button.text()).toBe('Parar subagentes')
    })

    it('com um só subagente rodando o rótulo fica no singular', () => {
      const w = mount(SubagentStrip, { props: { sessionId: 's1', entries: [entry('a', 'running'), entry('b', 'failed')] } })
      expect(stop(w).text()).toBe('Parar subagente')
    })

    it('também aparece com a lista recolhida', () => {
      const entries = [entry('a', 'running'), entry('b', 'running'), entry('c', 'running'), entry('d', 'completed')]
      const w = mount(SubagentStrip, { props: { sessionId: 's1', entries } })
      expect(rows(w)).toHaveLength(0)
      expect(stop(w).text()).toBe('Parar subagentes')
    })

    it('some quando nenhum roda', async () => {
      const w = mount(SubagentStrip, { props: { sessionId: 's1', entries: [entry('a', 'running')] } })
      expect(stop(w).exists()).toBe(true)
      await w.setProps({ entries: [entry('a', 'stopped'), entry('b', 'completed')] })
      expect(stop(w).exists()).toBe(false)
      expect(w.find('[data-test="subagent-strip"]').exists()).toBe(true)
    })

    it('chama a rota da sessão com o cabeçalho do app e fica desabilitado durante o pedido', async () => {
      let release: (r: Response) => void = () => {}
      const fetchMock = routeFetch({
        'POST /api/sessions/s1/subagents/stop': () => new Promise<Response>((r) => { release = r }),
      })
      vi.stubGlobal('fetch', fetchMock)
      const w = mount(SubagentStrip, { props: { sessionId: 's1', entries: [entry('a', 'running')] } })
      await stop(w).trigger('click')
      expect(fetchMock).toHaveBeenCalledTimes(1)
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/sessions/s1/subagents/stop',
        expect.objectContaining({ method: 'POST', headers: expect.objectContaining({ 'X-Vibing': '1' }) }),
      )
      expect(stop(w).attributes('disabled')).toBeDefined()
      await stop(w).trigger('click')
      expect(fetchMock).toHaveBeenCalledTimes(1)
      release(jsonResponse({}, 202))
      await flushPromises()
      expect(stop(w).attributes('disabled')).toBeUndefined()
      expect(w.find('[data-test="subagent-stop-error"]').exists()).toBe(false)
    })

    it('mostra o erro do servidor e permite tentar de novo', async () => {
      let status = 500
      vi.stubGlobal('fetch', routeFetch({
        'POST /api/sessions/s1/subagents/stop': () => (status === 500 ? jsonResponse({ detail: 'Não deu para parar.' }, 500) : jsonResponse({}, 202)),
      }))
      const w = mount(SubagentStrip, { props: { sessionId: 's1', entries: [entry('a', 'running')] } })
      await stop(w).trigger('click')
      await flushPromises()
      const error = w.find('[data-test="subagent-stop-error"]')
      expect(error.text()).toContain('Não deu para parar.')
      expect(error.attributes('role')).toBe('alert')
      expect(stop(w).attributes('disabled')).toBeUndefined()
      status = 202
      await stop(w).trigger('click')
      await flushPromises()
      expect(w.find('[data-test="subagent-stop-error"]').exists()).toBe(false)
    })
  })
})
