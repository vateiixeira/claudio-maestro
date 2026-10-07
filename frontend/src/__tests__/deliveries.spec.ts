import { describe, expect, it } from 'vitest'
import { deliveriesMarkdown, deliveryTitle, formatDayLong, groupByProject, localDay, projectMarkdown, rulerLayout, shiftDay } from '../deliveries'
import type { DeliveriesDay, Delivery } from '../types/api'

function delivery(over: Partial<Delivery> = {}): Delivery {
  return { id: 1, session_id: 's1', project_id: 1, project_name: 'app', title: 'Conversa', finished_at: 0,
    status: 'done', summary_title: 'Leitura de markdown', bullets: ['Rota', 'Página'], error: null, ...over }
}

describe('deliveries', () => {
  it('calcula o dia local e anda entre dias', () => {
    expect(localDay(new Date(2026, 9, 7, 23, 59))).toBe('2026-10-07')
    expect(shiftDay('2026-10-01', -1)).toBe('2026-09-30')
    expect(shiftDay('2026-12-31', 1)).toBe('2027-01-01')
  })

  it('escreve o dia por extenso com a primeira letra maiúscula', () => {
    expect(formatDayLong('2026-10-07')).toBe('Quarta-feira, 7 de outubro')
  })

  it('usa o título do agente, senão o da conversa', () => {
    expect(deliveryTitle(delivery())).toBe('Leitura de markdown')
    expect(deliveryTitle(delivery({ summary_title: null }))).toBe('Conversa')
  })

  it('agrupa por projeto mantendo a ordem', () => {
    const groups = groupByProject([delivery({ id: 1 }), delivery({ id: 2, project_name: 'b' }), delivery({ id: 3 })])
    expect(groups.map((g) => [g.project, g.items.map((d) => d.id)])).toEqual([['app', [1, 3]], ['b', [2]]])
  })

  it('gera o markdown do dia', () => {
    const day: DeliveriesDay = {
      date: '2026-10-07', agent_enabled: true,
      deliveries: [delivery(), delivery({ id: 2, summary_title: null, title: 'Só título', bullets: [], status: 'title_only' })],
      in_progress: [{ session_id: 'x', project_id: 1, project_name: 'app', title: 'Tela de entregas', short: null }],
      prev_day: null, next_day: null,
    }
    expect(deliveriesMarkdown(day)).toBe(
      '## Quarta-feira, 7 de outubro\n\n### app\n**Leitura de markdown**\n- Rota\n- Página\n\n**Só título**\n\n### Em andamento\n- app: Tela de entregas\n',
    )
  })

  it('omite "Em andamento" vazio e avisa quando o dia não tem nada', () => {
    const empty: DeliveriesDay = { date: '2026-10-07', agent_enabled: false, deliveries: [], in_progress: [], prev_day: null, next_day: null }
    expect(deliveriesMarkdown(empty)).toBe('## Quarta-feira, 7 de outubro\n\nNada finalizado neste dia.\n')
  })
  it('gera o markdown de um projeto, sem "Em andamento"', () => {
    const day: DeliveriesDay = {
      date: '2026-10-07', agent_enabled: true,
      deliveries: [delivery(), delivery({ id: 2, project_name: 'b', summary_title: 'Outra', bullets: ['x'] }), delivery({ id: 3, summary_title: null, title: 'Só título', bullets: [], status: 'title_only' })],
      in_progress: [{ session_id: 'x', project_id: 1, project_name: 'app', title: 'Tela', short: null }],
      prev_day: null, next_day: null,
    }
    expect(projectMarkdown(day, 'app')).toBe(
      '## Quarta-feira, 7 de outubro\n\n### app\n**Leitura de markdown**\n- Rota\n- Página\n\n**Só título**\n',
    )
  })
})

const at = (h: number, m = 0) => Math.floor(new Date(2026, 9, 7, h, m).getTime() / 1000)

describe('rulerLayout', () => {
  it('vai da hora cheia anterior à primeira até a seguinte à última', () => {
    const layout = rulerLayout([delivery({ id: 1, finished_at: at(10, 42) }), delivery({ id: 2, finished_at: at(14, 23) })])
    expect(layout.startHour).toBe(10)
    expect(layout.endHour).toBe(15)
    expect(layout.marks.map((m) => m.id)).toEqual([1, 2])
    expect(layout.marks[0]!.left).toBeCloseTo((42 / 300) * 100)
    expect(layout.marks[1]!.left).toBeCloseTo(((4 * 60 + 23) / 300) * 100)
  })

  it('usa pelo menos 2 horas, com uma entrega só ou na mesma hora', () => {
    const one = rulerLayout([delivery({ finished_at: at(10, 42) })])
    expect([one.startHour, one.endHour]).toEqual([10, 12])
    expect(one.marks[0]!.left).toBeCloseTo(35)
    const same = rulerLayout([delivery({ id: 1, finished_at: at(9, 5) }), delivery({ id: 2, finished_at: at(9, 50) })])
    expect([same.startHour, same.endHour]).toEqual([9, 11])
  })

  it('não passa de meia-noite nem antes dela', () => {
    const late = rulerLayout([delivery({ finished_at: at(23, 30) })])
    expect([late.startHour, late.endHour]).toEqual([22, 24])
    expect(late.marks[0]!.left).toBeCloseTo(((90) / 120) * 100)
  })

  it('empilha pontos próximos em até 3 níveis', () => {
    const same = [1, 2, 3, 4].map((id) => delivery({ id, finished_at: at(10, 30) }))
    const far = delivery({ id: 5, finished_at: at(14, 30) })
    const layout = rulerLayout([...same, far])
    expect(layout.marks.map((m) => m.row)).toEqual([0, 1, 2, 0, 0])
  })

  it('mantém na mesma linha os pontos que não se encostam', () => {
    const layout = rulerLayout([delivery({ id: 1, finished_at: at(10, 0) }), delivery({ id: 2, finished_at: at(11, 0) })])
    expect(layout.marks.map((m) => m.row)).toEqual([0, 0])
  })

  it('sem entregas não há faixa nem pontos', () => {
    expect(rulerLayout([])).toEqual({ startHour: 0, endHour: 0, marks: [] })
  })
})
