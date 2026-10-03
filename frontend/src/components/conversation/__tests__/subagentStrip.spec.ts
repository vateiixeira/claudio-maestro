import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { jsonResponse, routeFetch } from '../../../test/factories'
import { clockNow } from '../../../minuteClock'
import SubagentStrip from '../SubagentStrip.vue'
import type { SubagentEntry } from '../../../conversation/subagents'

const entry = (id: string, status: SubagentEntry['status'], extra: Partial<SubagentEntry> = {}): SubagentEntry => ({
  id, type: 'agent', kind: 'reviewer', description: `desc ${id}`, status, lastAction: `Read ${id}.py`, startedAt: null, lastActivityAt: null, ...extra,
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

  describe('comandos em background', () => {
    const command = (id: string, status: SubagentEntry['status']) => entry(id, status, { type: 'command', kind: 'Comando', lastAction: '' })

    it('a linha mostra "Comando", a descrição e o estado do comando', async () => {
      const w = mount(SubagentStrip, { props: { sessionId: 's1', entries: [command('a', 'running'), command('b', 'completed'), command('c', 'failed'), command('d', 'stopped')] } })
      await w.find('[data-test="subagent-summary"]').trigger('click')
      const first = rows(w)[0]!
      expect(first.text()).toContain('Comando')
      expect(first.text()).toContain('desc a')
      expect(first.text()).toContain('Em background')
      expect(first.find('[data-status="running"]').attributes('aria-label')).toBe('Em background')
      expect(rows(w)[1]!.text()).toContain('Concluído')
      expect(rows(w)[2]!.text()).toContain('Falhou')
      expect(rows(w)[3]!.text()).toContain('Parado')
      expect(first.find('[data-test="subagent-last-action"]').exists()).toBe(false)
    })

    it('rodando em âmbar (espera), concluído continua verde', () => {
      const w = mount(SubagentStrip, { props: { sessionId: 's1', entries: [command('a', 'running'), entry('b', 'running'), entry('c', 'completed')] } })
      for (const row of [rows(w)[0]!, rows(w)[1]!]) {
        expect(row.find('[data-status="running"] svg').classes()).toContain('text-secondary')
        expect(row.find('[data-status="running"] svg').classes()).not.toContain('text-primary')
        expect(row.find('.text-secondary-soft').exists()).toBe(true)
      }
      expect(rows(w)[2]!.find('[data-status="completed"] svg').classes()).toContain('text-primary')
    })

    it('o indicador do resumo recolhido também é âmbar', () => {
      const entries = [command('a', 'running'), command('b', 'running'), command('c', 'running'), command('d', 'completed')]
      const w = mount(SubagentStrip, { props: { sessionId: 's1', entries } })
      expect(w.find('[data-test="subagent-summary"] svg').classes()).toContain('text-secondary')
    })

    it('clicar na linha de um comando pede para ir ao cartão', async () => {
      const w = mount(SubagentStrip, { props: { sessionId: 's1', entries: [command('a', 'running')] } })
      await rows(w)[0]!.trigger('click')
      expect(w.emitted('select')).toEqual([['a']])
    })

    it('o botão deixa de falar só em subagentes', () => {
      const stop = (entries: SubagentEntry[]) => mount(SubagentStrip, { props: { sessionId: 's1', entries } }).find('[data-test="subagent-stop"]').text()
      expect(stop([command('a', 'running')])).toBe('Parar comando')
      expect(stop([command('a', 'running'), command('b', 'running')])).toBe('Parar comandos')
      expect(stop([command('a', 'running'), entry('b', 'running')])).toBe('Parar tarefas')
      expect(stop([command('a', 'running'), entry('b', 'completed')])).toBe('Parar comando')
      expect(stop([command('a', 'completed'), entry('b', 'running')])).toBe('Parar subagente')
    })

    it('a região e o resumo recolhido falam em tarefas em background quando há comandos', () => {
      const only = mount(SubagentStrip, { props: { sessionId: 's1', entries: [entry('a', 'running')] } })
      expect(only.find('[data-test="subagent-strip"]').attributes('aria-label')).toBe('Subagentes')
      const mixed = mount(SubagentStrip, { props: { sessionId: 's1', entries: [command('a', 'running'), entry('b', 'running'), entry('c', 'running'), entry('d', 'completed')] } })
      expect(mixed.find('[data-test="subagent-strip"]').attributes('aria-label')).toBe('Tarefas em background')
      expect(mixed.find('[data-test="subagent-summary"]').text()).toContain('Tarefas em background')
      expect(mixed.find('[data-test="subagent-summary"]').text()).toContain('3 rodando, 1 concluído')
    })
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
        expect.objectContaining({ method: 'POST', headers: expect.objectContaining({ 'X-Maestro': '1' }) }),
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

  describe('tempo de cada subagente', () => {
    const NOW = new Date('2026-10-03T12:00:00Z')
    const ago = (minutes: number) => Math.floor(NOW.getTime() / 1000) - minutes * 60
    const time = (w: ReturnType<typeof mount>, index = 0) => rows(w)[index]!.find('[data-test="subagent-time"]')

    beforeEach(() => {
      vi.useFakeTimers()
      vi.setSystemTime(NOW)
      clockNow.value = Date.now()
    })
    afterEach(() => {
      vi.useRealTimers()
    })

    it('mostra há quanto tempo o subagente roda, em mono, antes do estado', () => {
      const w = mount(SubagentStrip, { props: { sessionId: 's1', entries: [entry('a', 'running', { startedAt: ago(3), lastActivityAt: ago(1) })] } })
      const el = time(w)
      expect(el.text()).toBe('3 min')
      expect(el.classes()).toContain('font-mono')
      expect(el.classes()).toContain('tabular-nums')
      expect(el.classes()).toContain('text-fg-subtle')
      expect(el.attributes('title')).toBeUndefined()
      const spans = rows(w)[0]!.findAll('span').map((x) => x.text())
      expect(spans.indexOf('3 min')).toBeLessThan(spans.indexOf('Rodando'))
    })

    it('atualiza com o relógio do minuto', async () => {
      const w = mount(SubagentStrip, { props: { sessionId: 's1', entries: [entry('a', 'running', { startedAt: ago(3), lastActivityAt: ago(0) })] } })
      expect(time(w).text()).toBe('3 min')
      vi.setSystemTime(new Date(NOW.getTime() + 2 * 60_000))
      clockNow.value = Date.now()
      await w.vm.$nextTick()
      expect(time(w).text()).toBe('5 min')
    })

    it('rodando sem atividade há mais de 10 minutos: tempo em secondary-soft com aviso', () => {
      const w = mount(SubagentStrip, { props: { sessionId: 's1', entries: [entry('a', 'running', { startedAt: ago(30), lastActivityAt: ago(11) })] } })
      expect(time(w).classes()).toContain('text-secondary-soft')
      expect(time(w).classes()).not.toContain('text-fg-subtle')
      expect(time(w).attributes('title')).toBe('Sem atividade há algum tempo')
    })

    it('com atividade nos últimos 10 minutos não avisa', () => {
      const w = mount(SubagentStrip, { props: { sessionId: 's1', entries: [entry('a', 'running', { startedAt: ago(30), lastActivityAt: ago(9) })] } })
      expect(time(w).classes()).toContain('text-fg-subtle')
      expect(time(w).attributes('title')).toBeUndefined()
    })

    it('sem o momento da última atividade não avisa de parado', () => {
      const w = mount(SubagentStrip, { props: { sessionId: 's1', entries: [entry('a', 'running', { startedAt: ago(30), lastActivityAt: null })] } })
      expect(time(w).text()).toBe('30 min')
      expect(time(w).classes()).toContain('text-fg-subtle')
    })

    it('sem started_at o tempo não aparece', () => {
      const w = mount(SubagentStrip, { props: { sessionId: 's1', entries: [entry('a', 'running', { startedAt: null, lastActivityAt: null }), entry('b', 'running')] } })
      expect(time(w, 0).exists()).toBe(false)
      expect(time(w, 1).exists()).toBe(false)
    })

    it('comando em background não mostra tempo', () => {
      const w = mount(SubagentStrip, { props: { sessionId: 's1', entries: [entry('a', 'running', { type: 'command', startedAt: ago(3), lastActivityAt: ago(3) })] } })
      expect(time(w).exists()).toBe(false)
    })

    it('subagente que terminou mostra quanto durou, sem aviso', () => {
      const w = mount(SubagentStrip, { props: { sessionId: 's1', entries: [entry('a', 'running'), entry('b', 'completed', { startedAt: ago(40), lastActivityAt: ago(30) })] } })
      expect(time(w, 1).text()).toBe('10 min')
      expect(time(w, 1).classes()).toContain('text-fg-subtle')
    })
  })
})
