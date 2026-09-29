import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import QuestionCard from '../QuestionCard.vue'
import PlanCard from '../PlanCard.vue'
import { jsonResponse, routeFetch } from '../../../test/factories'
import type { PermissionPrompt } from '../../../types/conversation'

afterEach(() => vi.unstubAllGlobals())

const URL = 'POST /api/sessions/s1/prompts/p1'
const questionPrompt = (): PermissionPrompt => ({
  prompt_id: 'p1', tool_name: 'AskUserQuestion', input: {}, can_always: false, kind: 'question',
  questions: [
    { question: 'Qual banco?', header: 'Banco', multiSelect: false, options: [
      { label: 'Postgres', description: 'Relacional robusto' },
      { label: 'SQLite', description: 'Arquivo local' },
    ] },
    { question: 'Quais extras?', header: 'Extras', multiSelect: true, options: [
      { label: 'Cache', description: 'Redis' },
      { label: 'Fila', description: 'Celery' },
    ] },
  ],
})
const body = (m: ReturnType<typeof routeFetch>) => JSON.parse(m.mock.calls[0]![1]!.body as string)

describe('cartão de perguntas', () => {
  it('mostra perguntas, títulos, opções e descrições', () => {
    const w = mount(QuestionCard, { props: { sessionId: 's1', prompt: questionPrompt() } })
    expect(w.text()).toContain('Qual banco?')
    expect(w.text()).toContain('Banco')
    expect(w.text()).toContain('Relacional robusto')
    expect(w.findAll('input[type="radio"]')).toHaveLength(2)
    expect(w.findAll('input[type="checkbox"]')).toHaveLength(2)
  })

  it('só responde com todas as perguntas respondidas e envia answers', async () => {
    const fetchMock = routeFetch({ [URL]: () => jsonResponse({}) })
    vi.stubGlobal('fetch', fetchMock)
    const w = mount(QuestionCard, { props: { sessionId: 's1', prompt: questionPrompt() } })
    const submit = w.find('[data-test="answer"]')
    expect(submit.attributes('disabled')).toBeDefined()
    await w.findAll('input[type="radio"]')[1]!.setValue(true)
    expect(submit.attributes('disabled')).toBeDefined()
    await w.findAll('input[type="checkbox"]')[0]!.setValue(true)
    await w.findAll('input[type="checkbox"]')[1]!.setValue(true)
    expect(submit.attributes('disabled')).toBeUndefined()
    await submit.trigger('click')
    await flushPromises()
    expect(body(fetchMock)).toEqual({
      decision: 'answer',
      answers: { 'Qual banco?': 'SQLite', 'Quais extras?': ['Cache', 'Fila'] },
    })
    expect(w.emitted('resolved')).toHaveLength(1)
  })

  it('texto livre em "Outra resposta" substitui a opção', async () => {
    const fetchMock = routeFetch({ [URL]: () => jsonResponse({}) })
    vi.stubGlobal('fetch', fetchMock)
    const w = mount(QuestionCard, { props: { sessionId: 's1', prompt: questionPrompt() } })
    const others = w.findAll('[data-test="other-answer"]')
    await others[0]!.setValue('MySQL')
    await others[1]!.setValue('Nenhum')
    await w.find('[data-test="answer"]').trigger('click')
    await flushPromises()
    expect(body(fetchMock).answers).toEqual({ 'Qual banco?': 'MySQL', 'Quais extras?': ['Nenhum'] })
  })

  it('múltipla escolha avisa que "Outra resposta" substitui as marcadas', () => {
    const w = mount(QuestionCard, { props: { sessionId: 's1', prompt: questionPrompt() } })
    const hints = w.findAll('[data-test="other-hint"]')
    expect(hints).toHaveLength(1)
    expect(hints[0]!.text()).toContain('substitui')
  })

  it('recusar envia deny', async () => {
    const fetchMock = routeFetch({ [URL]: () => jsonResponse({}) })
    vi.stubGlobal('fetch', fetchMock)
    const w = mount(QuestionCard, { props: { sessionId: 's1', prompt: questionPrompt() } })
    await w.find('[data-test="deny"]').trigger('click')
    await flushPromises()
    expect(body(fetchMock)).toEqual({ decision: 'deny' })
  })

  it('400 mostra o detail', async () => {
    vi.stubGlobal('fetch', routeFetch({ [URL]: () => jsonResponse({ detail: 'Resposta inválida.' }, 400) }))
    const w = mount(QuestionCard, { props: { sessionId: 's1', prompt: questionPrompt() } })
    await w.find('[data-test="deny"]').trigger('click')
    await flushPromises()
    expect(w.find('[role="alert"]').text()).toContain('Resposta inválida.')
    expect(w.emitted('resolved')).toBeUndefined()
  })

  it('opções agrupadas em fieldset com legend, acessíveis pelo teclado', () => {
    const w = mount(QuestionCard, { props: { sessionId: 's1', prompt: questionPrompt() } })
    expect(w.findAll('fieldset')).toHaveLength(2)
    expect(w.find('legend').text()).toContain('Qual banco?')
    expect(w.findAll('label input')).toHaveLength(6)
  })
})

const planPrompt = (plan = '# Plano\n\n1. **Criar** tabela\n\n<script>alert(1)</script>'): PermissionPrompt => ({
  prompt_id: 'p1', tool_name: 'ExitPlanMode', input: {}, can_always: false, kind: 'plan', plan,
})

describe('cartão de plano', () => {
  it('renderiza o markdown sem HTML cru', () => {
    const w = mount(PlanCard, { props: { sessionId: 's1', prompt: planPrompt() } })
    expect(w.find('h1').text()).toBe('Plano')
    expect(w.find('strong').text()).toBe('Criar')
    expect(w.find('script').exists()).toBe(false)
  })

  it('aprovar envia approve', async () => {
    const fetchMock = routeFetch({ [URL]: () => jsonResponse({}) })
    vi.stubGlobal('fetch', fetchMock)
    const w = mount(PlanCard, { props: { sessionId: 's1', prompt: planPrompt() } })
    await w.find('[data-test="approve"]').trigger('click')
    await flushPromises()
    expect(body(fetchMock)).toEqual({ decision: 'approve' })
    expect(w.emitted('resolved')).toHaveLength(1)
  })

  it('pedir mudanças exige mensagem e envia reject', async () => {
    const fetchMock = routeFetch({ [URL]: () => jsonResponse({}) })
    vi.stubGlobal('fetch', fetchMock)
    const w = mount(PlanCard, { props: { sessionId: 's1', prompt: planPrompt() } })
    expect(w.find('[data-test="reject-message"]').exists()).toBe(false)
    await w.find('[data-test="request-changes"]').trigger('click')
    const send = w.find('[data-test="send-reject"]')
    expect(send.attributes('disabled')).toBeDefined()
    await w.find('[data-test="reject-message"]').setValue('   ')
    expect(send.attributes('disabled')).toBeDefined()
    await w.find('[data-test="reject-message"]').setValue('Use migrations')
    await send.trigger('click')
    await flushPromises()
    expect(body(fetchMock)).toEqual({ decision: 'reject', message: 'Use migrations' })
  })
})
