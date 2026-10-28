import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import DecisionCard from '../DecisionCard.vue'
import { jsonResponse, makeDecision, routeFetch } from '../../../../test/factories'

enableAutoUnmount(afterEach)
beforeEach(() => setActivePinia(createPinia()))
afterEach(() => vi.unstubAllGlobals())

const answeredBody = (answer: string) => makeDecision({ id: 4, status: 'answered', answer, receipt: 'abcd1234-0000', answered_at: 1_790_000_500 })

describe('DecisionCard', () => {
  it('mostra a pergunta na raiz do cartão', () => {
    const w = mount(DecisionCard, { props: { decision: makeDecision({ id: 4, question: 'Podemos migrar o banco?' }) } })
    expect(w.attributes('data-test')).toBe('decision-card')
    expect(w.text()).toContain('Podemos migrar o banco?')
  })

  it('opções viram botões', async () => {
    const fetch = routeFetch({ 'POST /api/decisions/4/answer': () => jsonResponse(answeredBody('Sim')) })
    vi.stubGlobal('fetch', fetch)
    const w = mount(DecisionCard, { props: { decision: makeDecision({ id: 4, options: ['Sim', 'Não'] }) } })
    const options = w.findAll('[data-test="decision-option"]')
    expect(options.map((o) => o.text())).toEqual(['Sim', 'Não'])
    expect(w.find('textarea').exists()).toBe(false)
    expect(w.get('[data-test="decision-submit"]').attributes('disabled')).toBeDefined()

    await options[0]!.trigger('click')
    expect(options[0]!.attributes('aria-pressed')).toBe('true')
    expect(options[1]!.attributes('aria-pressed')).toBe('false')
    await w.get('[data-test="decision-submit"]').trigger('click')
    await flushPromises()

    const call = fetch.mock.calls[0]!
    expect(call[0]).toBe('/api/decisions/4/answer')
    expect(JSON.parse(String(call[1]?.body))).toEqual({ answer: 'Sim' })
    // Answered: the answer and the receipt, no more buttons.
    expect(w.get('[data-test="decision-answer"]').text()).toBe('Sim')
    expect(w.get('[data-test="decision-receipt"]').text()).toContain('abcd1234')
    expect(w.find('[data-test="decision-option"]').exists()).toBe(false)
    expect(w.emitted('answered')).toHaveLength(1)
  })

  it('sem opções pede uma resposta livre', async () => {
    const fetch = routeFetch({ 'POST /api/decisions/4/answer': () => jsonResponse(answeredBody('Só em homologação')) })
    vi.stubGlobal('fetch', fetch)
    const w = mount(DecisionCard, { props: { decision: makeDecision({ id: 4, options: [] }) } })
    expect(w.find('[data-test="decision-option"]').exists()).toBe(false)
    expect(w.get('[data-test="decision-submit"]').attributes('disabled')).toBeDefined()
    await w.get('textarea').setValue('  Só em homologação ')
    await w.get('[data-test="decision-submit"]').trigger('click')
    await flushPromises()
    expect(JSON.parse(String(fetch.mock.calls[0]![1]?.body))).toEqual({ answer: 'Só em homologação' })
    expect(w.get('[data-test="decision-answer"]').text()).toBe('Só em homologação')
  })

  it('clique duplo envia uma resposta só', async () => {
    let done!: (r: Response) => void
    const fetch = vi.fn(() => new Promise<Response>((resolve) => { done = resolve }))
    vi.stubGlobal('fetch', fetch)
    const w = mount(DecisionCard, { props: { decision: makeDecision({ id: 4 }) } })
    await w.findAll('[data-test="decision-option"]')[0]!.trigger('click')
    await w.get('[data-test="decision-submit"]').trigger('click')
    await w.get('[data-test="decision-submit"]').trigger('click')
    expect(fetch).toHaveBeenCalledTimes(1)
    done(jsonResponse(answeredBody('Sim')))
    await flushPromises()
  })

  it('segunda resposta mostra já respondida', async () => {
    const fetch = routeFetch({ 'POST /api/decisions/4/answer': () => jsonResponse({ detail: 'A decisão já foi respondida.' }, 409) })
    vi.stubGlobal('fetch', fetch)
    const w = mount(DecisionCard, { props: { decision: makeDecision({ id: 4 }) } })
    await w.findAll('[data-test="decision-option"]')[1]!.trigger('click')
    await w.get('[data-test="decision-submit"]').trigger('click')
    await flushPromises()
    expect(fetch).toHaveBeenCalledTimes(1)
    expect(w.get('[data-test="decision-already"]').text()).toContain('Já respondida')
    // No form left to send a third answer, and no duplicate "answered" event.
    expect(w.find('[data-test="decision-submit"]').exists()).toBe(false)
    expect(w.find('[data-test="decision-option"]').exists()).toBe(false)
    expect(w.emitted('answered')).toBeUndefined()
    expect(w.emitted('stale')).toHaveLength(1)
  })

  it('depois de um 409, a decisão recarregada como respondida mostra resposta e recibo', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'POST /api/decisions/4/answer': () => jsonResponse({ detail: 'A decisão já foi respondida.' }, 409) }))
    const w = mount(DecisionCard, { props: { decision: makeDecision({ id: 4 }) } })
    await w.findAll('[data-test="decision-option"]')[0]!.trigger('click')
    await w.get('[data-test="decision-submit"]').trigger('click')
    await flushPromises()
    expect(w.find('[data-test="decision-already"]').exists()).toBe(true)
    await w.setProps({ decision: makeDecision({ id: 4, status: 'answered', answer: 'Não', receipt: 'ff00ee11-1', answered_at: 1_790_000_900 }) })
    expect(w.find('[data-test="decision-already"]').exists()).toBe(false)
    expect(w.get('[data-test="decision-answer"]').text()).toBe('Não')
    expect(w.get('[data-test="decision-receipt"]').text()).toContain('ff00ee11')
  })

  it('resposta inválida (422) mostra o erro e deixa corrigir', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'POST /api/decisions/4/answer': () => jsonResponse({ detail: 'A resposta precisa ter de 1 a 3990 caracteres.' }, 422) }))
    const w = mount(DecisionCard, { props: { decision: makeDecision({ id: 4, options: [] }) } })
    await w.get('textarea').setValue('x')
    await w.get('[data-test="decision-submit"]').trigger('click')
    await flushPromises()
    expect(w.get('[role="alert"]').text()).toContain('A resposta precisa ter de 1 a 3990 caracteres.')
    expect(w.find('[data-test="decision-already"]').exists()).toBe(false)
    expect(w.get('[data-test="decision-submit"]').attributes('disabled')).toBeUndefined()
  })

  it('decisão já respondida chega sem formulário, com resposta e recibo', () => {
    const w = mount(DecisionCard, { props: { decision: makeDecision({ id: 4, status: 'answered', answer: 'Não', receipt: 'ff00ee11-1', answered_at: 1_790_000_900 }) } })
    expect(w.find('[data-test="decision-submit"]').exists()).toBe(false)
    expect(w.get('[data-test="decision-answer"]').text()).toBe('Não')
    expect(w.get('[data-test="decision-receipt"]').text()).toContain('ff00ee11')
  })

  it('decisão expirada não oferece formulário', () => {
    const w = mount(DecisionCard, { props: { decision: makeDecision({ id: 4, status: 'expired' }) } })
    expect(w.find('[data-test="decision-submit"]').exists()).toBe(false)
    expect(w.get('[data-test="decision-expired"]').text()).toContain('Expirada')
  })

  it('trocar de decisão limpa a escolha anterior', async () => {
    const w = mount(DecisionCard, { props: { decision: makeDecision({ id: 4 }) } })
    await w.findAll('[data-test="decision-option"]')[0]!.trigger('click')
    await w.setProps({ decision: makeDecision({ id: 5, question: 'Outra?' }) })
    expect(w.findAll('[data-test="decision-option"]').every((o) => o.attributes('aria-pressed') === 'false')).toBe(true)
  })
})
