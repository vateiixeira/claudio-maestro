import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import PermissionCard from '../PermissionCard.vue'
import { jsonResponse, routeFetch } from '../../../test/factories'
import type { PermissionPrompt } from '../../../types/conversation'

afterEach(() => vi.unstubAllGlobals())

const prompt = (overrides: Partial<PermissionPrompt> = {}): PermissionPrompt => ({
  prompt_id: 'p1', tool_name: 'Bash', input: { command: 'rm -rf build' }, can_always: true, ...overrides,
})
const URL = 'POST /api/sessions/s1/prompts/p1'

describe('cartão de permissão', () => {
  it('mostra ferramenta e comando', () => {
    const w = mount(PermissionCard, { props: { sessionId: 's1', prompt: prompt() } })
    expect(w.text()).toContain('rm -rf build')
    expect(w.text()).toContain('Bash')
  })

  it.each([
    ['allow-once', 'allow_once'],
    ['deny', 'deny'],
    ['allow-always', 'allow_always'],
  ])('%s envia a decisão %s', async (button, decision) => {
    const fetchMock = routeFetch({ [URL]: () => jsonResponse({}) })
    vi.stubGlobal('fetch', fetchMock)
    const w = mount(PermissionCard, { props: { sessionId: 's1', prompt: prompt() } })
    await w.find(`[data-test="${button}"]`).trigger('click')
    expect(w.find(`[data-test="${button}"]`).attributes('disabled')).toBeDefined()
    await flushPromises()
    expect(JSON.parse(fetchMock.mock.calls[0]![1]!.body as string)).toEqual({ decision })
    expect(w.emitted('resolved')).toHaveLength(1)
  })

  it('"Permitir sempre" só aparece com can_always', () => {
    const w = mount(PermissionCard, { props: { sessionId: 's1', prompt: prompt({ can_always: false }) } })
    expect(w.find('[data-test="allow-always"]').exists()).toBe(false)
  })

  it('409 fecha o cartão sem erro', async () => {
    vi.stubGlobal('fetch', routeFetch({ [URL]: () => jsonResponse({ detail: 'Já respondido.' }, 409) }))
    const w = mount(PermissionCard, { props: { sessionId: 's1', prompt: prompt() } })
    await w.find('[data-test="deny"]').trigger('click')
    await flushPromises()
    expect(w.emitted('resolved')).toHaveLength(1)
    expect(w.find('[role="alert"]').exists()).toBe(false)
  })

  it('outro erro mostra o detail e reabilita os botões', async () => {
    vi.stubGlobal('fetch', routeFetch({ [URL]: () => jsonResponse({ detail: 'Sessão fechada.' }, 404) }))
    const w = mount(PermissionCard, { props: { sessionId: 's1', prompt: prompt() } })
    await w.find('[data-test="deny"]').trigger('click')
    await flushPromises()
    expect(w.emitted('resolved')).toBeUndefined()
    expect(w.find('[role="alert"]').text()).toContain('Sessão fechada.')
    expect(w.find('[data-test="deny"]').attributes('disabled')).toBeUndefined()
  })
})
