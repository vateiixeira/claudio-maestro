import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, mount } from '@vue/test-utils'
import { createMemoryHistory } from 'vue-router'
import RunLine from '../RunLine.vue'
import { runLines, type RunLine as Line } from '../runDays'
import { createAppRouter } from '../../../../router'
import { makeRun } from '../../../../test/factories'
import type { Run } from '../../../../types/org'

enableAutoUnmount(afterEach)

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(new Date(2026, 10, 17, 10, 40))
})
afterEach(() => vi.useRealTimers())

const at = (day: number, hour: number, minute: number, second = 0) => new Date(2026, 10, day, hour, minute, second).getTime() / 1000
const names: Record<number, string> = { 1: 'Triagem', 2: 'Revisor' }
const agentName = (id: number) => names[id] ?? null

async function mountLine(line: Line, extra: { maxSeconds?: number; all?: Run[] } = {}) {
  const router = createAppRouter(createMemoryHistory())
  await router.push('/')
  await router.isReady()
  return mount(RunLine, {
    props: { line, agentName, maxSeconds: extra.maxSeconds ?? 600, all: extra.all ?? [] },
    global: { plugins: [router] },
  })
}
const single = (run: Run): Line => ({ kind: 'run', run })

describe('RunLine', () => {
  it('mostra o agente, a hora e o início em ISO', async () => {
    const run = makeRun({ id: 1, agent_id: 1, started_at: at(13, 18, 40), ended_at: at(13, 18, 41), outcome: 'concluded' })
    const w = await mountLine(single(run))
    expect(w.get('[data-test="run-row"]').attributes('data-run-id')).toBe('1')
    expect(w.get('[data-test="run-agent"]').text()).toBe('Triagem')
    expect(w.get('[data-test="run-started"]').text()).toBe('18:40')
    expect(w.get('[data-test="run-started"]').attributes('datetime')).toBe(new Date(run.started_at * 1000).toISOString())
    expect(w.get('[data-test="run-outcome"]').attributes('data-shape')).toBe('check')
    expect(w.get('[data-test="run-outcome"]').find('svg').attributes('aria-label')).toBe('Concluída')
    expect(w.get('[data-test="run-duration"]').text()).toBe('1 min')
  })

  it('o título é a primeira linha do relato, senão o motivo, senão o resultado', async () => {
    const base = { agent_id: 1, started_at: at(13, 18, 40), ended_at: at(13, 18, 41) }
    const a = await mountLine(single(makeRun({ ...base, outcome: 'concluded', summary: 'Triei 3 chamados.\nDois urgentes.' })))
    expect(a.get('[data-test="run-headline"]').text()).toBe('Triei 3 chamados.')
    const b = await mountLine(single(makeRun({ ...base, outcome: 'failed', reason: 'O token expirou.' })))
    expect(b.get('[data-test="run-headline"]').text()).toBe('O token expirou.')
    const c = await mountLine(single(makeRun({ ...base, outcome: 'missed' })))
    expect(c.get('[data-test="run-headline"]').text()).toBe('Perdida')
    const d = await mountLine(single(makeRun({ ...base, ended_at: null, outcome: 'running' })))
    expect(d.get('[data-test="run-headline"]').text()).toBe('Rodando')
  })

  it('perdidas no mesmo minuto viram uma linha só, sem abrir', async () => {
    const t = at(10, 9, 4)
    const lines = runLines([
      makeRun({ id: 1, agent_id: 1, started_at: t, ended_at: t, outcome: 'missed' }),
      makeRun({ id: 2, agent_id: 2, started_at: t + 20, ended_at: t + 20, outcome: 'missed' }),
    ])
    const w = await mountLine(lines[0]!)
    const row = w.get('[data-test="run-row"]')
    expect(row.attributes('data-group-size')).toBe('2')
    expect(w.get('[data-test="run-headline"]').text()).toBe('2 perdidas: Revisor e Triagem')
    expect(w.get('[data-test="run-agent"]').text()).toBe('2 agentes')
    expect(w.get('[data-test="run-started"]').text()).toBe('09:04')
    expect(w.find('[data-test="run-toggle"]').exists()).toBe(false)
  })

  it('abre os detalhes: relato, origem, tarefa e conversa', async () => {
    const run = makeRun({
      id: 5, agent_id: 1, session_id: 'abc', source: 'routine', task_id: 7, started_at: at(13, 18, 40), ended_at: at(13, 18, 45),
      outcome: 'concluded', summary: 'Triei 3 chamados.\nDois urgentes.',
    })
    const w = await mountLine(single(run))
    const toggle = w.get('[data-test="run-toggle"]')
    expect(toggle.attributes('aria-expanded')).toBe('false')
    expect(w.find('[data-test="run-details"]').exists()).toBe(false)
    await toggle.trigger('click')
    expect(toggle.attributes('aria-expanded')).toBe('true')
    expect(toggle.attributes('aria-controls')).toBe(w.get('[data-test="run-details"]').attributes('id'))
    expect(w.get('[data-test="run-summary"]').text()).toContain('Dois urgentes.')
    expect(w.get('[data-test="run-source"]').text()).toBe('Rotina')
    expect(w.get('[data-test="run-task"]').text()).toBe('#7')
    expect(w.get('[data-test="run-task"]').attributes('href')).toBe('/tarefas/7')
    expect(w.get('[data-test="run-session"]').text()).toBe('Abrir conversa')
    expect(w.get('[data-test="run-session"]').attributes('href')).toBe('/sessions/abc')
    await toggle.trigger('click')
    expect(toggle.attributes('aria-expanded')).toBe('false')
    expect(w.find('[data-test="run-details"]').exists()).toBe(false)
  })

  it('um relato longo mostra o começo e o botão de ler inteiro', async () => {
    const long = `${'palavra '.repeat(60)}FIM`
    const w = await mountLine(single(makeRun({ agent_id: 1, started_at: at(13, 18, 40), ended_at: at(13, 18, 41), outcome: 'concluded', summary: long })))
    await w.get('[data-test="run-toggle"]').trigger('click')
    const more = w.get('[data-test="run-summary-more"]')
    expect(more.text()).toBe('Ler o relato inteiro')
    expect(w.get('[data-test="run-summary"]').text()).not.toContain('FIM')
    await more.trigger('click')
    expect(more.text()).toBe('Mostrar menos')
    expect(more.attributes('aria-expanded')).toBe('true')
    expect(w.get('[data-test="run-summary"]').text()).toContain('FIM')
    await more.trigger('click')
    expect(w.get('[data-test="run-summary"]').text()).not.toContain('FIM')
  })

  it('um relato curto não tem o botão', async () => {
    const w = await mountLine(single(makeRun({ agent_id: 1, started_at: at(13, 18, 40), ended_at: at(13, 18, 41), outcome: 'concluded', summary: 'Curto.' })))
    await w.get('[data-test="run-toggle"]').trigger('click')
    expect(w.find('[data-test="run-summary-more"]').exists()).toBe(false)
  })

  it('destaca a execução lenta frente à mediana da rotina', async () => {
    const mk = (id: number, seconds: number) =>
      makeRun({ id, agent_id: 1, routine_id: 3, source: 'routine', started_at: at(10 + id, 8, 0), ended_at: at(10 + id, 8, 0) + seconds, outcome: 'concluded' })
    const all = [mk(1, 60), mk(2, 60), mk(3, 60), mk(4, 60), mk(5, 1500)]
    const slow = await mountLine(single(all[4]!), { all, maxSeconds: 1500 })
    expect(slow.get('[data-test="run-duration-bar"]').attributes('data-slow')).toBe('true')
    expect(slow.get('[data-test="run-duration-bar"]').attributes('style')).toContain('width: 100%')
    await slow.get('[data-test="run-toggle"]').trigger('click')
    expect(slow.get('[data-test="run-slow"]').text()).toBe('Levou 25 vezes mais que o normal desta rotina')
    const normal = await mountLine(single(all[0]!), { all, maxSeconds: 1500 })
    expect(normal.get('[data-test="run-duration-bar"]').attributes('data-slow')).toBe('false')
    await normal.get('[data-test="run-toggle"]').trigger('click')
    expect(normal.find('[data-test="run-slow"]').exists()).toBe(false)
  })

  it('execução rodando, sem relato e sem duração, não quebra a linha nem a barra', async () => {
    const run = makeRun({ id: 9, agent_id: 1, started_at: at(17, 10, 30), ended_at: null, outcome: 'running', summary: null, reason: null })
    const w = await mountLine(single(run), { maxSeconds: 0, all: [run] })
    expect(w.get('[data-test="run-headline"]').text()).toBe('Rodando')
    expect(w.find('[data-test="run-duration"]').exists()).toBe(false)
    expect(w.find('[data-test="run-duration-bar"]').exists()).toBe(false)
    await w.get('[data-test="run-toggle"]').trigger('click')
    expect(w.find('[data-test="run-summary"]').exists()).toBe(false)
    expect(w.find('[data-test="run-slow"]').exists()).toBe(false)
  })

  it('a barra de uma execução que terminou com o maior tempo zero fica no mínimo', async () => {
    const run = makeRun({ id: 9, agent_id: 1, started_at: at(17, 10, 30), ended_at: at(17, 10, 30), outcome: 'concluded' })
    const w = await mountLine(single(run), { maxSeconds: 0, all: [run, run] })
    expect(w.get('[data-test="run-duration-bar"]').attributes('data-slow')).toBe('false')
    expect(w.get('[data-test="run-duration"]').text()).toBe('0 s')
  })

  it('o motivo aparece nos detalhes quando o título é outro', async () => {
    const run = makeRun({ agent_id: 1, started_at: at(13, 18, 40), ended_at: at(13, 18, 41), outcome: 'failed', reason: 'O token expirou.', summary: 'Tentei abrir o PR.' })
    const w = await mountLine(single(run))
    await w.get('[data-test="run-toggle"]').trigger('click')
    expect(w.get('[data-test="run-reason"]').text()).toBe('O token expirou.')
  })
})
