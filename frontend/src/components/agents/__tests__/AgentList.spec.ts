import { afterEach, describe, expect, it } from 'vitest'
import { enableAutoUnmount, mount } from '@vue/test-utils'
import { createMemoryHistory } from 'vue-router'
import AgentList from '../AgentList.vue'
import { createAppRouter } from '../../../router'
import { makeSpecialist, makeSpecialistRun } from '../../../test/factories'
import type { Specialist, SpecialistRunOutcome } from '../../../types/api'

enableAutoUnmount(afterEach)

async function mountList(agents: Specialist[], selectedId: number | null = null, loading = false) {
  const router = createAppRouter(createMemoryHistory())
  await router.push('/agentes')
  return mount(AgentList, { props: { agents, selectedId, loading }, global: { plugins: [router] } })
}

describe('AgentList', () => {
  it.each<[SpecialistRunOutcome, string]>([
    ['running', 'spinner'],
    ['starting', 'spinner'],
    ['queued', 'clock'],
    ['cancelled', 'dash'],
    ['concluded', 'check'],
    ['closed', 'check'],
    ['waiting', 'triangle'],
    ['failed', 'cross'],
    ['skipped', 'dash'],
    ['missed', 'dash'],
  ])('desfecho %s aparece como %s', async (outcome, shape) => {
    const w = await mountList([makeSpecialist({ last_run: makeSpecialistRun({ outcome }) })])
    expect(w.get('[data-test="agent-state"]').attributes('data-shape')).toBe(shape)
    // o estado nunca depende só da forma e da cor: há texto para leitor de tela
    expect(w.get('[data-test="agent-state"]').text()).not.toBe('')
  })

  it('sem execução ainda, mostra um marcador neutro', async () => {
    const w = await mountList([makeSpecialist({ last_run: null })])
    expect(w.get('[data-test="agent-state"]').attributes('data-shape')).toBe('none')
  })

  it('mostra o próximo horário ou "sem horário"', async () => {
    const w = await mountList([
      makeSpecialist({ id: 1, schedules: [{ id: 1, days: '1234567', time: '08:40', last_fired_at: null }] }),
      makeSpecialist({ id: 2, name: 'Filmes', schedules: [] }),
    ])
    const [first, second] = w.findAll('[data-test="agent-next"]')
    expect(first!.text()).toMatch(/^próximo: (seg|ter|qua|qui|sex|sáb|dom) 08:40$/)
    expect(second!.text()).toBe('sem horário')
  })

  // T7: tela antiga sem rota (a organização ocupa /agentes); o arquivo e este teste saem na limpeza.

  it.skip('cada agente leva a /agentes/:id e o aberto fica marcado', async () => {
    const w = await mountList([makeSpecialist({ id: 1 }), makeSpecialist({ id: 2, name: 'Filmes' })], 2)
    const items = w.findAll('[data-test="agent-item"]')
    expect(items.map((i) => i.attributes('href'))).toEqual(['/agentes/1', '/agentes/2'])
    expect(items[1]!.attributes('aria-current')).toBe('page')
    expect(items[0]!.attributes('aria-current')).toBeUndefined()
  })

  it('enquanto a lista carrega, mostra "Carregando…" e não "Nenhum agente ainda."', async () => {
    const w = await mountList([], null, true)
    expect(w.text()).toContain('Carregando…')
    expect(w.text()).not.toContain('Nenhum agente ainda')
  })

  it('"Novo agente" avisa quem usa o componente', async () => {
    const w = await mountList([])
    await w.get('[data-test="agent-new"]').trigger('click')
    expect(w.emitted('new')).toHaveLength(1)
    expect(w.text()).toContain('Nenhum agente ainda')
  })
})

it('oferece um seletor compacto de agente e ações de criação e GitHub', async () => {
  const w = await mountList([makeSpecialist({ id: 1 }), makeSpecialist({ id: 2, name: 'Filmes' })], 2)
  expect(w.get('[data-test="agent-picker-toggle"]').text()).toContain('Filmes')
  expect(w.find('[data-test="agent-new"]').exists()).toBe(true)
  expect(w.find('[data-test="agents-github-open"]').exists()).toBe(true)
  await w.get('[data-test="agent-picker-toggle"]').trigger('click')
  expect(w.findAll('[data-test="agent-item"]')).toHaveLength(2)
})
