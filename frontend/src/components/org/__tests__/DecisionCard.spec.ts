import { afterEach, describe, expect, it } from 'vitest'
import { enableAutoUnmount, mount } from '@vue/test-utils'
import DecisionCard from '../tasks/DecisionCard.vue'
import { makeDecision } from '../../../test/factories'

enableAutoUnmount(afterEach)

describe('DecisionCard (casca)', () => {
  it('mostra a pergunta da decisão', () => {
    const w = mount(DecisionCard, { props: { decision: makeDecision({ question: 'Podemos migrar o banco?' }) } })
    expect(w.attributes('data-test')).toBe('decision-card')
    expect(w.text()).toContain('Podemos migrar o banco?')
  })
})
