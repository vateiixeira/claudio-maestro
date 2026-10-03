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

const STEPS_PLAN = '# Plano\n\n### Tarefa 1: Criar tabela\n- [ ] a\n\n### Tarefa 2: Expor rota\n- [ ] b\n\n### Tarefa 3: Testar\n- [ ] c\n'

describe('cartão de plano com passos', () => {
  const mountSteps = () => mount(PlanCard, { props: { sessionId: 's1', prompt: planPrompt(STEPS_PLAN) } })
  const openChanges = async (w: ReturnType<typeof mountSteps>) => w.find('[data-test="request-changes"]').trigger('click')

  it('sem pedir mudanças não mostra a lista de passos', () => {
    expect(mountSteps().find('[data-test="plan-steps"]').exists()).toBe(false)
  })

  it('ao pedir mudanças lista os passos numerados e esconde o campo único', async () => {
    const w = mountSteps()
    await openChanges(w)
    const steps = w.findAll('[data-test="plan-step"]')
    expect(steps).toHaveLength(3)
    expect(steps[0]!.text()).toContain('1')
    expect(steps[0]!.text()).toContain('Criar tabela')
    expect(steps[2]!.text()).toContain('Testar')
    expect(w.find('[data-test="reject-message"]').exists()).toBe(false)
    expect(w.find('[data-test="general-comment"]').exists()).toBe(true)
    expect(w.find('[data-test="send-reject"]').attributes('disabled')).toBeDefined()
  })

  it('clicar num passo abre o campo de uma linha, e a nota fica abaixo dele', async () => {
    const w = mountSteps()
    await openChanges(w)
    expect(w.find('[data-test="step-note"]').exists()).toBe(false)
    await w.findAll('[data-test="plan-step"]')[1]!.trigger('click')
    const input = w.find('[data-test="step-note"]')
    expect(input.attributes('placeholder')).toBe('O que mudar neste passo')
    await input.setValue('Usar PATCH')
    await input.trigger('keydown.enter')
    expect(w.find('[data-test="step-note"]').exists()).toBe(false)
    const note = w.find('[data-test="step-note-text"]')
    expect(note.text()).toBe('Usar PATCH')
    expect(w.findAll('[data-test="plan-step"]')[1]!.find('[data-test="step-number"]').classes()).toContain('text-secondary-soft')
    expect(w.findAll('[data-test="plan-step"]')[0]!.find('[data-test="step-number"]').classes()).not.toContain('text-secondary-soft')
  })

  it('clicar num passo leva o foco ao campo que abre', async () => {
    const w = mount(PlanCard, { props: { sessionId: 's1', prompt: planPrompt(STEPS_PLAN) }, attachTo: document.body })
    await openChanges(w)
    await w.findAll('[data-test="plan-step"]')[1]!.trigger('click')
    await flushPromises()
    expect(document.activeElement).toBe(w.find('[data-test="step-note"]').element)
    w.unmount()
  })

  it('qualquer anotação habilita o envio e o pedido junta os passos e o comentário geral', async () => {
    const fetchMock = routeFetch({ [URL]: () => jsonResponse({}) })
    vi.stubGlobal('fetch', fetchMock)
    const w = mountSteps()
    await openChanges(w)
    const send = w.find('[data-test="send-reject"]')
    await w.findAll('[data-test="plan-step"]')[2]!.trigger('click')
    await w.find('[data-test="step-note"]').setValue('Cobrir o erro 409')
    expect(send.attributes('disabled')).toBeUndefined()
    await w.findAll('[data-test="plan-step"]')[0]!.trigger('click')
    await w.find('[data-test="step-note"]').setValue('  Usar migration  ')
    await w.find('[data-test="general-comment"]').setValue('Sem mexer no front')
    await send.trigger('click')
    await flushPromises()
    expect(body(fetchMock)).toEqual({
      decision: 'reject',
      message: 'Passo 1: Usar migration\nPasso 3: Cobrir o erro 409\nSem mexer no front',
    })
    expect(w.emitted('resolved')).toHaveLength(1)
  })

  it('dois passos com o mesmo número têm anotações separadas', async () => {
    const fetchMock = routeFetch({ [URL]: () => jsonResponse({}) })
    vi.stubGlobal('fetch', fetchMock)
    const dup = '# Plano\n\n### Tarefa 1: Criar tabela\n- [ ] a\n\n### Tarefa 1: Expor rota\n- [ ] b\n'
    const w = mount(PlanCard, { props: { sessionId: 's1', prompt: planPrompt(dup) } })
    await openChanges(w)
    await w.findAll('[data-test="plan-step"]')[1]!.trigger('click')
    await w.find('[data-test="step-note"]').setValue('Só a rota')
    await w.findAll('[data-test="plan-step"]')[0]!.trigger('click')
    expect(w.find('[data-test="step-note"]').element).toHaveProperty('value', '')
    expect(w.findAll('[data-test="step-note-text"]')).toHaveLength(1)
    expect(w.findAll('[data-test="plan-step"]')[1]!.find('[data-test="step-number"]').classes()).toContain('text-secondary-soft')
    expect(w.findAll('[data-test="plan-step"]')[0]!.find('[data-test="step-number"]').classes()).not.toContain('text-secondary-soft')
    await w.find('[data-test="send-reject"]').trigger('click')
    await flushPromises()
    expect(body(fetchMock)).toEqual({ decision: 'reject', message: 'Passo 1: Só a rota' })
  })

  it('só o comentário geral já habilita o envio', async () => {
    const fetchMock = routeFetch({ [URL]: () => jsonResponse({}) })
    vi.stubGlobal('fetch', fetchMock)
    const w = mountSteps()
    await openChanges(w)
    await w.find('[data-test="general-comment"]').setValue('Muito longo')
    await w.find('[data-test="send-reject"]').trigger('click')
    await flushPromises()
    expect(body(fetchMock)).toEqual({ decision: 'reject', message: 'Muito longo' })
  })

  it('nota apagada ou só com espaços não conta como anotação', async () => {
    const w = mountSteps()
    await openChanges(w)
    await w.findAll('[data-test="plan-step"]')[0]!.trigger('click')
    await w.find('[data-test="step-note"]').setValue('   ')
    expect(w.find('[data-test="send-reject"]').attributes('disabled')).toBeDefined()
  })

  it('plano sem passos reconhecidos mantém o campo único de hoje', async () => {
    const w = mount(PlanCard, { props: { sessionId: 's1', prompt: planPrompt() } })
    await w.find('[data-test="request-changes"]').trigger('click')
    expect(w.find('[data-test="plan-step"]').exists()).toBe(false)
    expect(w.find('[data-test="general-comment"]').exists()).toBe(false)
    expect(w.find('[data-test="reject-message"]').exists()).toBe(true)
  })
})

describe('entrada ao vivo dos cartões de pergunta e de plano', () => {
  const planPrompt = (): PermissionPrompt => ({ prompt_id: 'p1', tool_name: 'ExitPlanMode', input: {}, can_always: false, kind: 'plan', plan: '# Plano' })

  it('pergunta: a animação de decisão só vem com live', () => {
    const history = mount(QuestionCard, { props: { sessionId: 's1', prompt: questionPrompt() } })
    expect(history.find('[data-test="question-card"]').classes()).not.toContain('animate-decision')
    const live = mount(QuestionCard, { props: { sessionId: 's1', prompt: questionPrompt(), live: true } })
    expect(live.find('[data-test="question-card"]').classes()).toContain('animate-decision')
  })

  it('plano: a animação de decisão só vem com live', () => {
    const history = mount(PlanCard, { props: { sessionId: 's1', prompt: planPrompt() } })
    expect(history.find('[data-test="plan-card"]').classes()).not.toContain('animate-decision')
    const live = mount(PlanCard, { props: { sessionId: 's1', prompt: planPrompt(), live: true } })
    expect(live.find('[data-test="plan-card"]').classes()).toContain('animate-decision')
  })
})
