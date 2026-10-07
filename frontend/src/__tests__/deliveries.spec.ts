import { describe, expect, it } from 'vitest'
import { deliveriesMarkdown, deliveryTitle, formatDayLong, groupByProject, localDay, shiftDay } from '../deliveries'
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
    }
    expect(deliveriesMarkdown(day)).toBe(
      '## Quarta-feira, 7 de outubro\n\n### app\n**Leitura de markdown**\n- Rota\n- Página\n\n**Só título**\n\n### Em andamento\n- app: Tela de entregas\n',
    )
  })

  it('omite "Em andamento" vazio e avisa quando o dia não tem nada', () => {
    const empty: DeliveriesDay = { date: '2026-10-07', agent_enabled: false, deliveries: [], in_progress: [] }
    expect(deliveriesMarkdown(empty)).toBe('## Quarta-feira, 7 de outubro\n\nNada finalizado neste dia.\n')
  })
})
