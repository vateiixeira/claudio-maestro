import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { enableAutoUnmount, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import { createAppRouter } from '../../../../router'
import TaskThread from '../TaskThread.vue'
import { useOrgStore } from '../../../../stores/org'
import { makeAgent, makeComment } from '../../../../test/factories'

enableAutoUnmount(afterEach)
let pinia: Pinia

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  useOrgStore(pinia).agents = [makeAgent({ id: 2, slug: 'dev', name: 'Dev', busy: true })]
})

const router = createAppRouter(createMemoryHistory())

function mountThread(comments = [
  makeComment({ id: 3, author_kind: 'app', text: 'Tarefa passou para Em revisão.', created_at: 1_790_000_300 }),
  makeComment({ id: 1, author_kind: 'human', text: 'Pode começar.', created_at: 1_790_000_100 }),
  makeComment({ id: 2, author_kind: 'agent', author_agent_id: 2, text: 'Feito, abri o **PR**.', created_at: 1_790_000_200 }),
]) {
  return mount(TaskThread, { props: { comments }, global: { plugins: [pinia, router] } })
}

describe('TaskThread', () => {
  it('humano à direita, agente com nome, app discreto', () => {
    const w = mountThread()
    const items = w.findAll('[data-test="task-comment"]')
    expect(items.map((i) => i.attributes('data-author'))).toEqual(['human', 'agent', 'app'])

    const human = items[0]!
    expect(human.classes()).toContain('self-end')
    expect(human.text()).toContain('Pode começar.')
    expect(human.find('[data-test="comment-author"]').exists()).toBe(false)

    const agent = items[1]!
    expect(agent.classes()).toContain('self-start')
    expect(agent.get('[data-test="comment-author"]').text()).toBe('Dev')
    expect(agent.get('[data-test="agent-state"]').attributes('data-state')).toBe('busy')
    expect(agent.get('strong').text()).toBe('PR')
    // Any link to an agent goes to its panel in the organization of its project.
    expect(agent.get('[data-test="comment-author"]').attributes('href')).toBe('/agentes/1?agente=2')

    const app = items[2]!
    expect(app.classes()).toContain('self-center')
    expect(app.classes()).toContain('text-fg-subtle')
    expect(app.text()).toContain('Tarefa passou para Em revisão.')
    expect(app.find('[data-test="comment-author"]').exists()).toBe(false)
  })

  it('texto com HTML não vira marcação', () => {
    const w = mountThread([makeComment({ text: '<img src=x onerror=alert(1)>' })])
    expect(w.find('img').exists()).toBe(false)
  })

  it('agente que não está mais na organização aparece como Agente removido', () => {
    const w = mountThread([makeComment({ author_kind: 'agent', author_agent_id: 77, text: 'Oi' })])
    expect(w.get('[data-test="comment-author"]').text()).toBe('Agente removido')
  })

  it('sem comentários diz que ninguém comentou', () => {
    const w = mountThread([])
    expect(w.get('[data-test="thread-empty"]').text()).toBe('Nenhum comentário ainda.')
  })
})
