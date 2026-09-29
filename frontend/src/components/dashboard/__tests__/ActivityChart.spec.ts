import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ActivityChart from '../ActivityChart.vue'
import { makeProject } from '../../../test/factories'

const projects = [makeProject({ id: 1, name: 'a', color: '#ff0000' }), makeProject({ id: 2, name: 'b', color: '#00ff00' })]
const today = new Date(2026, 8, 29, 15)

describe('gráfico de atividade', () => {
  it('empilha as barras por projeto em cada dia', () => {
    const wrapper = mount(ActivityChart, { props: { projects, days: 14, today, data: [
      { date: '2026-09-29', project_id: 1, sessions: 2 },
      { date: '2026-09-29', project_id: 2, sessions: 1 },
      { date: '2026-09-20', project_id: 1, sessions: 1 },
    ] } })

    const bars = wrapper.findAll('[data-test="activity-bar"]')
    expect(bars).toHaveLength(3)
    const last = bars.filter((b) => b.attributes('data-date') === '2026-09-29')
    expect(last.map((b) => b.attributes('fill'))).toEqual(['#ff0000', '#00ff00'])
    expect(wrapper.find('table').text()).toContain('29/09')
  })

  it('mostra o estado vazio', () => {
    const wrapper = mount(ActivityChart, { props: { projects, days: 14, today, data: [] } })
    expect(wrapper.find('[data-test="activity-empty"]').text()).toBe('Nenhuma atividade nos últimos 14 dias.')
  })
})
