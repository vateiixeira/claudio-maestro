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
  describe('diff de Edit, Write e MultiEdit', () => {
    const numbered = (n: number) => Array.from({ length: n }, (_, i) => `linha ${i + 1}`).join('\n')

    it('Edit mostra o diff, o caminho e as contagens no lugar do texto cru', () => {
      const w = mount(PermissionCard, {
        props: { sessionId: 's1', prompt: prompt({ tool_name: 'Edit', input: { file_path: '/p/a.ts', old_string: 'um', new_string: 'dois' } }) },
      })
      const well = w.find('[data-test="permission-diff"]')
      expect(well.exists()).toBe(true)
      expect(well.classes()).toEqual(expect.arrayContaining(['bg-bg', 'border-line']))
      expect(well.find('[data-test="diff-path"]').text()).toBe('/p/a.ts')
      expect(well.find('[data-test="diff-path"]').classes()).toContain('text-info-soft')
      expect(well.find('[data-test="diff-counts"]').text()).toContain('+1')
      expect(well.find('[data-test="diff-counts"]').text()).toContain('−1')
      const kinds = w.findAll('[data-test="diff-line"]').map((l) => l.attributes('data-kind'))
      expect(kinds).toEqual(['del', 'add'])
      expect(w.find('pre').exists()).toBe(false)
    })

    it('Write mostra as linhas como adicionadas', () => {
      const w = mount(PermissionCard, {
        props: { sessionId: 's1', prompt: prompt({ tool_name: 'Write', input: { file_path: '/p/novo.md', content: 'a\nb' } }) },
      })
      expect(w.findAll('[data-test="diff-line"]').map((l) => l.attributes('data-kind'))).toEqual(['add', 'add'])
      expect(w.find('[data-test="diff-counts"]').text()).toContain('+2')
    })

    it('MultiEdit junta o diff de cada edição', () => {
      const w = mount(PermissionCard, {
        props: {
          sessionId: 's1',
          prompt: prompt({ tool_name: 'MultiEdit', input: { file_path: '/p/a.ts', edits: [{ old_string: 'a', new_string: 'b' }, { old_string: 'c', new_string: 'd' }] } }),
        },
      })
      expect(w.findAll('[data-test="diff-line"]')).toHaveLength(4)
    })

    it('até 12 linhas aparece tudo, sem botão', () => {
      const w = mount(PermissionCard, {
        props: { sessionId: 's1', prompt: prompt({ tool_name: 'Write', input: { file_path: '/p/a.md', content: numbered(12) } }) },
      })
      expect(w.findAll('[data-test="diff-line"]')).toHaveLength(12)
      expect(w.find('[data-test="diff-expand"]').exists()).toBe(false)
    })

    it('acima de 12 linhas recolhe e "Ver as N linhas" expande', async () => {
      const w = mount(PermissionCard, {
        props: { sessionId: 's1', prompt: prompt({ tool_name: 'Write', input: { file_path: '/p/a.md', content: numbered(30) } }) },
      })
      expect(w.findAll('[data-test="diff-line"]')).toHaveLength(12)
      const expand = w.find('[data-test="diff-expand"]')
      expect(expand.text()).toBe('Ver as 30 linhas')
      await expand.trigger('click')
      expect(w.findAll('[data-test="diff-line"]')).toHaveLength(30)
      expect(w.find('[data-test="diff-expand"]').exists()).toBe(false)
    })

    it('Edit sem conteúdo para comparar cai no texto de antes', () => {
      const w = mount(PermissionCard, {
        props: { sessionId: 's1', prompt: prompt({ tool_name: 'Edit', input: { file_path: '/p/a.ts' } }) },
      })
      expect(w.find('[data-test="permission-diff"]').exists()).toBe(false)
      expect(w.text()).toContain('/p/a.ts')
    })

    it('Bash continua sem diff', () => {
      const w = mount(PermissionCard, { props: { sessionId: 's1', prompt: prompt() } })
      expect(w.find('[data-test="permission-diff"]').exists()).toBe(false)
    })
  })

  describe('regra de "Permitir sempre"', () => {
    const suggestions = [{ type: 'addRules', behavior: 'allow', destination: 'localSettings', rules: [{ toolName: 'Bash', ruleContent: 'pnpm test:*' }] }]

    it('descreve a regra e onde ela vale, depois do botão', () => {
      const w = mount(PermissionCard, { props: { sessionId: 's1', prompt: prompt({ suggestions }) } })
      const hint = w.find('[data-test="rule-hint"]')
      expect(hint.exists()).toBe(true)
      expect(hint.text()).toContain('Libera')
      expect(hint.text()).toContain('neste projeto, só para você')
      const chip = hint.find('[data-test="rule-chip"]')
      expect(chip.text()).toBe('Bash(pnpm test:*)')
      expect(chip.classes()).toEqual(expect.arrayContaining(['font-mono', 'bg-bg', 'border-line']))
      expect(hint.classes()).toEqual(expect.arrayContaining(['text-xs', 'text-fg-muted']))
      const html = w.html()
      expect(html.indexOf('data-test="allow-always"')).toBeLessThan(html.indexOf('data-test="rule-hint"'))
    })

    it('setMode vira "Muda o modo para ..." sem chips', () => {
      const w = mount(PermissionCard, {
        props: { sessionId: 's1', prompt: prompt({ suggestions: [{ type: 'setMode', mode: 'acceptEdits', destination: 'session' }] }) },
      })
      const hint = w.find('[data-test="rule-hint"]')
      expect(hint.text()).toContain('Muda o modo para Aceitar edições')
      expect(hint.text()).toContain('só nesta sessão')
      expect(hint.find('[data-test="rule-chip"]').exists()).toBe(false)
    })

    it('sem can_always ou sem sugestões entendidas não mostra a dica', () => {
      expect(mount(PermissionCard, { props: { sessionId: 's1', prompt: prompt({ suggestions, can_always: false }) } }).find('[data-test="rule-hint"]').exists()).toBe(false)
      expect(mount(PermissionCard, { props: { sessionId: 's1', prompt: prompt({ suggestions: [] }) } }).find('[data-test="rule-hint"]').exists()).toBe(false)
      expect(mount(PermissionCard, { props: { sessionId: 's1', prompt: prompt({ suggestions: null }) } }).find('[data-test="rule-hint"]').exists()).toBe(false)
    })
  })
})
