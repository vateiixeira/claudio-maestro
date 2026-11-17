import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { enableAutoUnmount, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import StartSessionRow from '../StartSessionRow.vue'
import { createAppRouter } from '../../../router'
import { useProjectsStore } from '../../../stores/projects'
import { makeProject, makeSession } from '../../../test/factories'
import type { Session } from '../../../types/api'

enableAutoUnmount(afterEach)
let pinia: Pinia
const NOW = Math.floor(Date.now() / 1000)

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  useProjectsStore(pinia).projects = [makeProject({ id: 2, name: 'Loja', color: '#4fd1c5' })]
})

function row(overrides: Partial<Session> = {}) {
  const router = createAppRouter(createMemoryHistory())
  return mount(StartSessionRow, {
    props: { session: makeSession({ session_id: 'abc', project_id: 2, title: 'Revisar os pedidos', last_activity_at: NOW - 17 * 60, ...overrides }) },
    global: { plugins: [pinia, router] },
  })
}

describe('conversa esperando', () => {
  it('é um link para a conversa, com título, projeto, resumo curto e o tempo', () => {
    const w = row({ digest_short: 'Deploy em produção', unread: true })
    expect(w.element.tagName).toBe('A')
    expect(w.attributes('href')).toBe('/sessions/abc')
    expect(w.text()).toContain('Revisar os pedidos')
    expect(w.get('[data-test="project-tag"]').text()).toContain('Loja')
    expect(w.text()).toContain('Deploy em produção')
    expect(w.get('[data-test="start-row-time"]').text()).toBe('há 17 min')
    expect(w.find('[data-test="session-activity"]').exists()).toBe(false)
  })

  it('mostra o selo de fechamento', () => {
    const w = row({ closure_verdict: 'incomplete' })
    expect(w.get('[data-test="closure-badge"]').text()).toBe('Entrega incompleta')
  })

  it('mostra "Plano concluído" quando o plano acabou', () => {
    const w = row({ plan_done: true })
    expect(w.text()).toContain('Plano concluído')
  })

  it('o ícone avisa quando pede você e fica quieto quando só espera', () => {
    expect(row({ unread: true }).get('[data-shape]').attributes('data-shape')).toBe('triangle')
    expect(row({ unread: false }).get('[data-shape]').attributes('data-shape')).toBe('triangle-quiet')
  })

  it('sem resumo nem projeto conhecido não quebra', () => {
    const w = row({ project_id: 99, digest_short: null })
    expect(w.find('[data-test="project-tag"]').exists()).toBe(false)
    expect(w.text()).toContain('Revisar os pedidos')
  })
})

describe('conversa em execução', () => {
  it('mostra a linha de atividade e não o tempo', () => {
    const w = row({ display_state: 'running', state: 'running', last_action: 'Bash: npm test' })
    expect(w.get('[data-test="session-activity"]').text()).toContain('npm test')
    expect(w.find('[data-test="start-row-time"]').exists()).toBe(false)
    expect(w.get('[data-shape]').attributes('data-shape')).toBe('spinner')
  })

  it('sem título usa um texto no lugar', () => {
    expect(row({ display_state: 'running', title: '' }).text()).toContain('Conversa sem título')
  })
})
