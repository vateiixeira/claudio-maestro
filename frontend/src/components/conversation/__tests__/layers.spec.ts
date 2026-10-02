import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import { createAppRouter } from '../../../router'
import { jsonResponse, makeProject, makeSnapshot, routeFetch } from '../../../test/factories'
import { useProjectsStore } from '../../../stores/projects'
import { useGitStore } from '../../../stores/git'
import ConversationBlock from '../ConversationBlock.vue'
import type { ConversationItem } from '../../../types/conversation'

vi.mock('../../../api/socket', () => ({
  useEventSocket: () => ({
    onSession: () => () => {},
    onReconnect: () => () => {},
    onOpen: () => () => {},
  }),
}))

import ConversationThread from '../ConversationThread.vue'

enableAutoUnmount(afterEach)
let pinia: Pinia
beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  const projects = useProjectsStore(pinia)
  projects.projects = [makeProject({ id: 1 })]
  projects.loaded = true
  useGitStore(pinia).set(1, [])
})
afterEach(() => vi.unstubAllGlobals())

function bash(result: { content: string; is_error: boolean } | null): ConversationItem {
  return {
    type: 'tool', id: 't1', tool_use_id: 'tu1', name: 'Bash', input: { command: 'ls -la' },
    result: result ? { ...result, details: null } : null, streaming: false, parent_tool_use_id: null,
  } as ConversationItem
}

describe('camadas visuais do chat (opção A)', () => {
  it('Bash: cabeçalho solto e uma caixa só, com IN e OUT separados por uma linha', () => {
    const w = mount(ConversationBlock, { props: { item: bash({ content: 'saida', is_error: false }), sessionActive: false } })
    expect(w.find('[data-test="bash-header"]').classes()).not.toContain('bg-panel')
    const box = w.find('[data-test="bash-box"]')
    expect(box.classes()).toEqual(expect.arrayContaining(['bg-panel', 'border', 'border-line']))
    const cmd = box.find('[data-test="bash-command"]')
    expect(cmd.text()).toContain('IN')
    expect(cmd.text()).toContain('ls -la')
    const out = box.find('[data-test="bash-output"]')
    expect(out.classes()).toEqual(expect.arrayContaining(['border-t', 'border-line']))
    expect(out.text()).toContain('OUT')
    expect(out.text()).toContain('saida')
  })

  it('Bash com erro mantém a saída em vermelho', () => {
    const w = mount(ConversationBlock, { props: { item: bash({ content: 'boom', is_error: true }), sessionActive: false } })
    expect(w.find('[data-test="tool-error"] [data-test="pane-toggle"]').classes()).toContain('text-diff-del-fg')
    expect(w.find('[data-test="bash-status-dot"]').attributes('data-state')).toBe('error')
  })

  it('TextBlock limita a largura de leitura a 90ch', () => {
    const w = mount(ConversationBlock, { props: { item: { type: 'text', id: 'x', text: 'oi', streaming: false, parent_tool_use_id: null } } })
    expect(w.find('.markdown').classes()).toContain('max-w-[90ch]')
  })

  it('mensagem do usuário é um balão à direita', () => {
    const w = mount(ConversationBlock, { props: { item: { type: 'user', id: 'u', text: 'oi', images: [] } } })
    expect(w.find('[data-test="user-message-row"]').classes()).toContain('justify-end')
    const card = w.find('[data-test="user-message-card"]')
    expect(card.classes()).toEqual(expect.arrayContaining(['bg-primary-tint', 'border-primary/25', 'rounded-br-md']))
    expect(card.classes()).not.toContain('bg-elevated')
    expect(w.find('[data-test="user-message"]').classes()).toContain('text-fg')
    // A posição diz quem falou; o leitor de tela ouve o nome.
    expect(card.find('.sr-only').text()).toBe('Você:')
  })

  it('anexos da mensagem do usuário acompanham o tom verde', () => {
    const item = { type: 'user', id: 'u', text: 'oi', images: [{ type: 'image', media_type: 'image/png', size: 2048 }] }
    const w = mount(ConversationBlock, { props: { item: item as never } })
    const chip = w.find('[data-test="attachment"]')
    expect(chip.text()).toContain('Imagem')
    expect(chip.classes()).toEqual(expect.arrayContaining(['border-primary/25', 'text-fg-muted']))
    expect(chip.classes()).not.toContain('bg-panel')
  })

  it('resposta do modelo vira balão à esquerda só no nível de cima', () => {
    const item: ConversationItem = { type: 'text', id: 'x', text: 'oi', streaming: false, parent_tool_use_id: null }
    const top = mount(ConversationBlock, { props: { item, bubble: true } })
    const bubble = top.find('[data-test="assistant-bubble"]')
    expect(bubble.classes()).toEqual(expect.arrayContaining(['bg-card', 'rounded-tl-md', 'w-fit']))
    // Dentro de subagente ou ferramenta continua texto solto, sem caixa dentro de caixa.
    const nested = mount(ConversationBlock, { props: { item } })
    expect(nested.find('[data-test="assistant-bubble"]').exists()).toBe(false)
  })

  it('rodapé do turno, trilho e superfície do chat', async () => {
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/sessions/s1': () => jsonResponse(makeSnapshot({
        seq: 1, state: 'running',
        items: [
          { type: 'user', id: 'u1', text: 'a' },
          { type: 'text', id: 'a', text: 'x', streaming: false, parent_tool_use_id: null },
          { type: 'user', id: 'u2', text: 'b' },
        ],
      })),
    }))
    const router = createAppRouter(createMemoryHistory())
    await router.push('/sessions/s1')
    const w = mount(ConversationThread, { props: { id: 's1', visible: true }, global: { plugins: [pinia, router] } })
    await flushPromises()
    const end = w.find('[data-test="turn-end"]')
    // Rodapé do turno: linha discreta, sem caixa; nos turnos antigos tudo em cinza.
    expect(end.classes()).not.toEqual(expect.arrayContaining(['bg-panel']))
    expect(end.find('[data-test="turn-end-label"]').classes()).toContain('text-fg-subtle')
    expect(end.find('.text-primary-soft').exists()).toBe(false)
    expect(w.html()).toContain('bg-line-strong')
    // As respostas do turno aparecem em balão.
    expect(w.findAll('[data-test="assistant-bubble"]')).toHaveLength(1)
  })
})
