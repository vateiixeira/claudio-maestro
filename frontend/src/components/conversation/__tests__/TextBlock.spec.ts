import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, type Pinia } from 'pinia'
import { computed } from 'vue'

vi.mock('../../../api/http', async (orig) => ({
  ...(await orig<typeof import('../../../api/http')>()),
  runInTerminal: vi.fn(),
  closeTerminal: vi.fn(),
}))

vi.mock('../../../api/terminalSocket', () => {
  class TerminalSocket {
    static instances: TerminalSocket[] = []
    frameCbs = new Set<(f: unknown) => void>()
    sessionId: string
    constructor(sessionId: string) {
      this.sessionId = sessionId
      TerminalSocket.instances.push(this)
    }
    onFrame(cb: (f: unknown) => void) {
      this.frameCbs.add(cb)
      return () => this.frameCbs.delete(cb)
    }
    onClose() {
      return () => {}
    }
    sendInput() {}
    resize() {}
    close() {}
    emit(frame: unknown) {
      this.frameCbs.forEach((cb) => cb(frame))
    }
  }
  return { TerminalSocket }
})

import { runInTerminal } from '../../../api/http'
import { TerminalSocket } from '../../../api/terminalSocket'
import { SESSION_ID_KEY } from '../../../stores/changesPanel'
import { useTerminalStore } from '../../../stores/terminal'
import PlanCard from '../PlanCard.vue'
import TextBlock from '../TextBlock.vue'
import type { PermissionPrompt, TextItem } from '../../../types/conversation'

const item = (text: string, over: Partial<TextItem> = {}): TextItem =>
  ({ type: 'text', id: 'm1', text, streaming: false, parent_tool_use_id: null, ...over }) as TextItem

const SOCKETS = TerminalSocket as unknown as { instances: Array<{ emit: (f: unknown) => void }> }

function mountBlock(text: string, over: Partial<TextItem> = {}, sessionId: string | null = 's1') {
  const pinia = createPinia()
  const wrapper = mount(TextBlock, {
    props: { item: item(text, over) },
    global: { plugins: [pinia], provide: sessionId ? { [SESSION_ID_KEY as symbol]: computed(() => sessionId) } : {} },
  })
  return { wrapper, pinia }
}

const label = (w: ReturnType<typeof mountBlock>['wrapper'], index = 0) =>
  w.findAll('[data-code-run]')[index]!.find('span').text()

describe('play nos blocos de comando', () => {
  beforeEach(() => {
    SOCKETS.instances.length = 0
    vi.mocked(runInTerminal).mockReset()
  })
  afterEach(() => vi.useRealTimers())

  it('clicar no play roda o comando com a chave do bloco', async () => {
    vi.mocked(runInTerminal).mockResolvedValue({ run_id: 'r1' })
    const { wrapper } = mountBlock('Rode:\n\n```bash\nls -la\n```\n\nE depois:\n\n```bash\npwd\n```')
    expect(wrapper.findAll('[data-code-run]')).toHaveLength(2)
    await wrapper.findAll('[data-code-run]')[1]!.trigger('click')
    await flushPromises()
    expect(runInTerminal).toHaveBeenCalledWith('s1', 'pwd')
    expect(label(wrapper, 1)).toBe('Rodando…')
    expect(wrapper.findAll('.code-block')[1]!.attributes('data-run-state')).toBe('starting')
    expect(wrapper.findAll('.code-block')[0]!.attributes('data-run-state')).toBe('idle')
  })

  it('a chave é "<id>:<índice>" e o frame sent com código 0 muda o rótulo', async () => {
    vi.mocked(runInTerminal).mockResolvedValue({ run_id: 'r1' })
    const { wrapper, pinia } = mountBlock('```bash\nls\n```')
    await wrapper.find('[data-code-run]').trigger('click')
    await flushPromises()
    expect(useTerminalStore(pinia).runStateFor('m1:0')).toBe('starting')
    SOCKETS.instances[0]!.emit({ type: 'run', run_id: 'r1', state: 'running', exit_code: null })
    await flushPromises()
    expect(label(wrapper)).toBe('Rodando…')
    SOCKETS.instances[0]!.emit({ type: 'run', run_id: 'r1', state: 'sent', exit_code: 0 })
    await flushPromises()
    expect(label(wrapper)).toBe('Enviado · código 0')
    expect(wrapper.find('.code-block').attributes('data-run-state')).toBe('sent')
  })

  it('a chave conta todos os blocos de código, não só os que rodam', async () => {
    vi.mocked(runInTerminal).mockResolvedValue({ run_id: 'r1' })
    const { wrapper, pinia } = mountBlock('```json\n{"a": 1}\n```\n\n```bash\nls\n```')
    await wrapper.find('[data-code-run]').trigger('click')
    await flushPromises()
    expect(useTerminalStore(pinia).runStateFor('m1:1')).toBe('starting')
  })

  it('o estado volta ao DOM depois de o texto crescer e refazer o HTML', async () => {
    vi.mocked(runInTerminal).mockResolvedValue({ run_id: 'r1' })
    const { wrapper } = mountBlock('```bash\nls\n```')
    await wrapper.find('[data-code-run]').trigger('click')
    await flushPromises()
    SOCKETS.instances[0]!.emit({ type: 'run', run_id: 'r1', state: 'sent', exit_code: 1 })
    await flushPromises()
    await wrapper.setProps({ item: item('```bash\nls\n```\n\nmais texto depois') })
    await flushPromises()
    expect(label(wrapper)).toBe('Enviado · código 1')
    expect(wrapper.find('.code-block').attributes('data-run-state')).toBe('sent')
  })

  it('o Copiar continua copiando só o código', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    const { wrapper } = mountBlock('```bash\nls\n```')
    await wrapper.find('[data-code-copy]').trigger('click')
    await flushPromises()
    expect(writeText).toHaveBeenCalledWith('ls\n')
    expect(runInTerminal).not.toHaveBeenCalled()
  })

  it('bloco que não é comando não tem play', () => {
    const { wrapper } = mountBlock('```json\n{"a": 1}\n```')
    expect(wrapper.find('[data-code-run]').exists()).toBe(false)
  })

  it('sem conversa não há play', () => {
    const { wrapper } = mountBlock('```bash\nls\n```', {}, null)
    expect(wrapper.find('[data-code-run]').exists()).toBe(false)
  })

  it('durante o streaming não há play', () => {
    const { wrapper } = mountBlock('```bash\nls\n```', { streaming: true })
    expect(wrapper.find('[data-code-run]').exists()).toBe(false)
  })

  it('o PlanCard não tem play', () => {
    const prompt = { prompt_id: 'p1', tool_name: 'ExitPlanMode', input: {}, kind: 'plan', can_always: false, plan: '# Plano\n\n```bash\nls\n```' } as PermissionPrompt
    const w = mount(PlanCard, { props: { sessionId: 's1', prompt }, global: { plugins: [createPinia() as Pinia] } })
    expect(w.find('.code-block').exists()).toBe(true)
    expect(w.find('[data-code-run]').exists()).toBe(false)
  })
})
