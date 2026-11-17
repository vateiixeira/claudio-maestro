import { afterEach, describe, expect, it } from 'vitest'
import { enableAutoUnmount, mount } from '@vue/test-utils'
import RoutineRow from '../RoutineRow.vue'
import { makeRoutine, makeRun } from '../../../../test/factories'
import type { Routine, Run } from '../../../../types/org'

enableAutoUnmount(afterEach)

// Tuesday, 10:40.
const now = new Date(2026, 10, 17, 10, 40)
const at = (day: number, h: number, m: number) => Math.floor(new Date(2026, 10, day, h, m).getTime() / 1000)

const routine = makeRoutine({
  id: 5, agent_id: 1, name: 'Sentry', enabled: true, instruction: 'Faça a triagem dos chamados novos.',
  schedules: [
    { id: 1, days: '1234567', time: '07:40', last_fired_at: null },
    { id: 2, days: '1234567', time: '18:40', last_fired_at: null },
  ],
})

function mountRow(props: { routine?: Routine; agentName?: string | null; agentEnabled?: boolean | null; runs?: Run[]; runsLoaded?: boolean } = {}) {
  return mount(RoutineRow, {
    props: {
      routine, agentName: 'Triagem', agentEnabled: true, runs: [], runsLoaded: true, now,
      ...props,
    },
  })
}

describe('RoutineRow', () => {
  it('mostra agente, agenda em frase e instrução', () => {
    const w = mountRow()
    expect(w.get('[data-test="routine-name-text"]').text()).toBe('Sentry')
    expect(w.get('[data-test="routine-agent-name"]').text()).toBe('agente Triagem')
    expect(w.get('[data-test="routine-schedules"]').text()).toBe('Todos os dias às 07:40 e às 18:40')
    expect(w.get('[data-test="routine-instruction-text"]').text()).toBe('Instrução: Faça a triagem dos chamados novos.')
    expect(w.get('[data-test="routine-next"]').text()).toBe('hoje 18:40')
    expect(w.find('[data-test="routine-blocked"]').exists()).toBe(false)
  })

  it('agente desligado: a próxima aparece e diz que não roda', () => {
    const w = mountRow({ agentEnabled: false })
    expect(w.get('[data-test="routine-next"]').text()).toBe('hoje 18:40')
    expect(w.get('[data-test="routine-blocked"]').text()).toBe('não roda: agente desligado')
  })

  it('rotina desligada: diz que não roda', () => {
    const w = mountRow({ routine: { ...routine, enabled: false } })
    expect(w.get('[data-test="routine-blocked"]').text()).toBe('não roda: rotina desligada')
    expect(w.get('[data-test="routine-toggle"]').attributes('aria-checked')).toBe('false')
  })

  it('sem horários: "sem horário" e nada de bloqueio', () => {
    const w = mountRow({ routine: { ...routine, schedules: [] } })
    expect(w.get('[data-test="routine-next"]').text()).toBe('sem horário')
    expect(w.get('[data-test="routine-schedules"]').text()).toBe('Sem horário')
    expect(w.find('[data-test="routine-blocked"]').exists()).toBe(false)
    expect(w.find('[data-test="routine-week-slot"]').exists()).toBe(false)
  })

  it('agente removido não quebra a linha', () => {
    const w = mountRow({ agentName: null, agentEnabled: null })
    expect(w.get('[data-test="routine-agent-name"]').text()).toBe('Agente removido')
    expect(w.get('[data-test="routine-blocked"]').text()).toBe('não roda: agente removido')
    expect(w.get('[data-test="routine-next"]').text()).toBe('hoje 18:40')
  })

  it('a chave é um switch que emite o novo estado', async () => {
    const w = mountRow()
    const toggle = w.get('[data-test="routine-toggle"]')
    expect(toggle.attributes('role')).toBe('switch')
    expect(toggle.attributes('aria-checked')).toBe('true')
    await toggle.trigger('click')
    expect(w.emitted('toggle')).toEqual([[false]])
  })

  it('ocupada: a chave fica desabilitada', () => {
    expect(mountRow().get('[data-test="routine-toggle"]').attributes('disabled')).toBeUndefined()
    const busy = mount(RoutineRow, { props: { routine, agentName: 'Triagem', agentEnabled: true, runs: [], runsLoaded: true, now, busy: true } })
    expect(busy.get('[data-test="routine-toggle"]').attributes('disabled')).toBeDefined()
  })

  it('a última concluída mostra data, duração e o histórico', () => {
    const runs = [
      makeRun({ id: 3, routine_id: 5, outcome: 'concluded', started_at: at(13, 18, 40), ended_at: at(13, 18, 40) + 1481 }),
      makeRun({ id: 2, routine_id: 5, outcome: 'missed', started_at: at(12, 18, 40), ended_at: null }),
    ]
    const w = mountRow({ runs })
    const last = w.get('[data-test="routine-last"]')
    expect(last.text()).toContain('13 nov 18:40')
    expect(last.text()).toContain('24 min 41 s')
    expect(last.find('[data-test="run-history"]').exists()).toBe(true)
  })

  it('a última perdida diz "perdida"; sem execuções, "ainda não rodou"', () => {
    const missed = mountRow({ runs: [makeRun({ routine_id: 5, outcome: 'missed', started_at: at(10, 9, 4), ended_at: null })] })
    expect(missed.get('[data-test="routine-last"]').text()).toContain('10 nov 09:04')
    expect(missed.get('[data-test="routine-last"]').text()).toContain('perdida')
    const none = mountRow()
    expect(none.get('[data-test="routine-last"]').text()).toContain('ainda não rodou')
    expect(none.find('[data-test="run-history"]').exists()).toBe(false)
  })

  it('sem as execuções do agente lidas, não afirma que ainda não rodou', () => {
    const w = mountRow({ runsLoaded: false })
    expect(w.get('[data-test="routine-last"]').text()).not.toContain('ainda não rodou')
    expect(w.get('[data-test="routine-last"]').text()).toContain('Última')
  })

  it('a última perdida mostra a hora agendada, não a da detecção', () => {
    const run = makeRun({ routine_id: 5, outcome: 'missed', scheduled_for: at(13, 18, 40), started_at: at(16, 10, 15), ended_at: null })
    expect(mountRow({ runs: [run] }).get('[data-test="routine-last"]').text()).toContain('13 nov 18:40')
  })

  it('o próximo horário na semana só fica verde quando a rotina roda', () => {
    const slot = (w: ReturnType<typeof mountRow>) => w.get('[data-test="routine-week-slot"][data-next="true"]')
    expect(slot(mountRow()).classes().join(' ')).toContain('text-primary-soft')
    for (const w of [mountRow({ agentEnabled: false }), mountRow({ routine: { ...routine, enabled: false } }), mountRow({ agentEnabled: null })]) {
      expect(slot(w).classes().join(' ')).not.toContain('primary')
    }
  })

  it('cria tarefa aparece como marca', () => {
    expect(mountRow({ routine: { ...routine, create_task: true } }).find('[data-test="routine-creates-task"]').exists()).toBe(true)
    expect(mountRow().find('[data-test="routine-creates-task"]').exists()).toBe(false)
  })

  it('rodar e editar emitem; o menu tem Excluir com confirmação', async () => {
    const w = mount(RoutineRow, { props: { routine, agentName: 'Triagem', agentEnabled: true, runs: [], runsLoaded: true, now }, attachTo: document.body })
    await w.get('[data-test="routine-run"]').trigger('click')
    await w.get('[data-test="routine-edit"]').trigger('click')
    expect(w.emitted('run')).toHaveLength(1)
    expect(w.emitted('edit')).toHaveLength(1)
    expect(w.find('[data-test="routine-delete"]').exists()).toBe(false)
    await w.get('[data-test="routine-more"]').trigger('click')
    const item = document.body.querySelector<HTMLElement>('[data-test="more-menu-item"][data-id="delete"]')!
    expect(item.textContent).toBe('Excluir')
    item.click()
    await w.vm.$nextTick()
    expect(w.emitted('delete')).toBeUndefined()
    expect(document.activeElement).toBe(w.get('[data-test="routine-delete-confirm"]').element)
    await w.get('[data-test="routine-delete-confirm"]').trigger('click')
    expect(w.emitted('delete')).toHaveLength(1)
  })

  it('cancelar a exclusão volta às ações', async () => {
    const w = mountRow()
    await w.get('[data-test="routine-more"]').trigger('click')
    document.body.querySelector<HTMLElement>('[data-test="more-menu-item"][data-id="delete"]')!.click()
    await w.vm.$nextTick()
    await w.get('[data-test="routine-delete-cancel"]').trigger('click')
    expect(w.find('[data-test="routine-delete-confirm"]').exists()).toBe(false)
    expect(w.find('[data-test="routine-run"]').exists()).toBe(true)
  })

  it('mostra o erro e o retorno da linha', () => {
    expect(mountRow().find('[data-test="routine-row-error"]').exists()).toBe(false)
    const w = mount(RoutineRow, { props: { routine, agentName: 'T', agentEnabled: true, runs: [], runsLoaded: true, now, feedback: { kind: 'error', text: 'Falhou.' } } })
    expect(w.get('[data-test="routine-row-error"]').attributes('role')).toBe('alert')
    const ok = mount(RoutineRow, { props: { routine, agentName: 'T', agentEnabled: true, runs: [], runsLoaded: true, now, feedback: { kind: 'ok', text: 'Rotina disparada.' } } })
    expect(ok.get('[data-test="routine-feedback"]').text()).toBe('Rotina disparada.')
  })

  it('traz a semana da rotina', () => {
    const w = mountRow()
    expect(w.findAll('[data-test="routine-week-day"]')).toHaveLength(7)
  })
})
