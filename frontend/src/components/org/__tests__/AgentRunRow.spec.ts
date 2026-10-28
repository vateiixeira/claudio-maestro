import { afterEach, describe, expect, it } from 'vitest'
import { enableAutoUnmount, mount } from '@vue/test-utils'
import { createMemoryHistory } from 'vue-router'
import AgentRunRow from '../agent/AgentRunRow.vue'
import { createAppRouter } from '../../../router'
import { makeRun } from '../../../test/factories'
import type { Run } from '../../../types/org'

enableAutoUnmount(afterEach)

async function mountRow(run: Partial<Run>, agentName?: string | null) {
  const router = createAppRouter(createMemoryHistory())
  await router.push('/agentes/1')
  await router.isReady()
  return mount(AgentRunRow, { props: { run: makeRun(run), agentName }, global: { plugins: [router] } })
}

describe('AgentRunRow', () => {
  it('mostra resultado com forma, origem, início e duração', async () => {
    const w = await mountRow({ outcome: 'concluded', source: 'routine', started_at: 1_790_000_000, ended_at: 1_790_000_090 })
    expect(w.attributes('data-test')).toBe('run-row')
    expect(w.element.tagName).toBe('LI')
    expect(w.get('[data-test="run-outcome"]').attributes('data-shape')).toBe('check')
    expect(w.get('[data-test="run-outcome"]').text()).toContain('Concluída')
    expect(w.get('[data-test="run-source"]').text()).toBe('Rotina')
    expect(w.get('[data-test="run-duration"]').text()).toBe('1 min 30 s')
    expect(w.find('time').exists()).toBe(true)
  })

  it('execução em andamento usa o círculo girando e não mostra duração final', async () => {
    const w = await mountRow({ outcome: 'running', ended_at: null })
    expect(w.get('[data-test="run-outcome"]').attributes('data-shape')).toBe('spinner')
    expect(w.find('[data-test="run-duration"]').exists()).toBe(false)
  })

  it('falha usa o xis e mostra o motivo', async () => {
    const w = await mountRow({ outcome: 'failed', reason: 'O processo caiu.', ended_at: 1_790_000_010 })
    expect(w.get('[data-test="run-outcome"]').attributes('data-shape')).toBe('cross')
    expect(w.get('[data-test="run-reason"]').text()).toBe('O processo caiu.')
  })

  it('liga à tarefa e à conversa quando existem', async () => {
    const w = await mountRow({ task_id: 12, session_id: 'sess-9', source: 'assignment' })
    expect(w.get('[data-test="run-task"]').attributes('href')).toBe('/tarefas/12')
    expect(w.get('[data-test="run-task"]').text()).toBe('#12')
    expect(w.get('[data-test="run-session"]').attributes('href')).toBe('/sessions/sess-9')
    expect(w.get('[data-test="run-session"]').text()).toBe('Abrir conversa')
  })

  it('sem tarefa nem sessão não mostra links', async () => {
    const w = await mountRow({ task_id: null, session_id: null })
    expect(w.find('[data-test="run-task"]').exists()).toBe(false)
    expect(w.find('[data-test="run-session"]').exists()).toBe(false)
  })

  it('mostra o nome do agente só quando ele vem', async () => {
    expect((await mountRow({})).find('[data-test="run-agent"]').exists()).toBe(false)
    const w = await mountRow({}, 'Revisora')
    expect(w.get('[data-test="run-agent"]').text()).toBe('Revisora')
  })
})
