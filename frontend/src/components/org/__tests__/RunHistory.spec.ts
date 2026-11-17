import { afterEach, describe, expect, it } from 'vitest'
import { enableAutoUnmount, mount } from '@vue/test-utils'
import RunHistory from '../RunHistory.vue'
import { makeRun } from '../../../test/factories'

enableAutoUnmount(afterEach)

describe('RunHistory', () => {
  it('desenha uma barra por execução terminada, da mais antiga para a mais nova', () => {
    const wrapper = mount(RunHistory, {
      props: {
        runs: [
          makeRun({ id: 3, outcome: 'missed' }),
          makeRun({ id: 2, outcome: 'failed' }),
          makeRun({ id: 1, outcome: 'concluded' }),
        ],
      },
    })
    const root = wrapper.get('[data-test="run-history"]')
    expect(root.attributes('role')).toBe('img')
    expect(root.attributes('aria-label')).toBe('Últimas 3 execuções: 1 concluída, 1 com falha, 1 perdida')
    expect(wrapper.findAll('[data-test="run-history-bar"]').map((b) => b.attributes('data-kind'))).toEqual(['ok', 'fail', 'miss'])
  })

  it('não desenha nada sem execuções terminadas', () => {
    expect(mount(RunHistory, { props: { runs: [] } }).find('[data-test="run-history"]').exists()).toBe(false)
    expect(mount(RunHistory, { props: { runs: [makeRun({ outcome: 'running' })] } }).find('[data-test="run-history"]').exists()).toBe(false)
  })
})
