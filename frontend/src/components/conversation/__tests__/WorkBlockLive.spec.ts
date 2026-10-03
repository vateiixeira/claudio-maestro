import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, mount } from '@vue/test-utils'
import { toRaw } from 'vue'
import type { ToolItem } from '../../../types/conversation'

const spies = vi.hoisted(() => ({ toolDiff: vi.fn() }))
vi.mock('../../../conversation/diff', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../conversation/diff')>()
  spies.toolDiff.mockImplementation(actual.toolDiff)
  return { ...actual, toolDiff: spies.toolDiff }
})

import WorkBlock from '../WorkBlock.vue'

enableAutoUnmount(afterEach)

const done = { content: 'ok', is_error: false, details: null }
function tool(id: string, name: string, input: Record<string, unknown> = {}, extra: Partial<ToolItem> = {}): ToolItem {
  return { type: 'tool', id, tool_use_id: `tu-${id}`, name, input, result: done, streaming: false, parent_tool_use_id: null, ...extra }
}
const NOW = new Date('2026-10-03T12:00:00Z')
const nowSeconds = () => Math.floor(NOW.getTime() / 1000)

type Props = { items: ToolItem[]; open?: boolean; sessionActive?: boolean; waitingIds?: ReadonlySet<string> }
const mountBlock = (props: Props) => mount(WorkBlock, { props: { open: true, sessionActive: true, ...props } })
const statusOf = (w: ReturnType<typeof mountBlock>, index: number) =>
  w.findAll('[data-test="work-row"]')[index]!.find('[data-test="work-status"]')

beforeEach(() => {
  spies.toolDiff.mockClear()
  vi.useFakeTimers()
  vi.setSystemTime(NOW)
})
const restores: Array<() => void> = []
afterEach(() => {
  restores.splice(0).forEach((restore) => restore())
  vi.useRealTimers()
})
// `restoreAllMocks` would also wipe the toolDiff spy's implementation.
function spyOnTimer(name: 'setInterval' | 'clearInterval') {
  const spy = vi.spyOn(globalThis, name)
  restores.push(() => spy.mockRestore())
  return spy
}

describe('WorkBlock: ferramenta esperando você', () => {
  const items = () => [tool('r', 'Read'), tool('b', 'Bash', { command: 'rm -rf x' }, { result: null })]

  it('a linha mostra "esperando você" e o resumo conta assim, em vez de rodando', () => {
    const w = mountBlock({ items: items(), waitingIds: new Set(['tu-b']) })
    expect(statusOf(w, 1).attributes('data-status')).toBe('waiting')
    expect(statusOf(w, 1).text()).toContain('esperando você')
    expect(statusOf(w, 1).find('.animate-spin').exists()).toBe(false)
    expect(w.find('[data-test="work-summary"]').text()).toBe('1 leitura · 1 esperando você')
  })

  it('sem o pedido pendente continua rodando', () => {
    const w = mountBlock({ items: items() })
    expect(statusOf(w, 1).attributes('data-status')).toBe('running')
    expect(w.find('[data-test="work-summary"]').text()).toBe('1 leitura · 1 rodando')
  })

  it('o pedido respondido volta a linha ao estado seguinte', async () => {
    const w = mountBlock({ items: items(), waitingIds: new Set(['tu-b']) })
    await w.setProps({ waitingIds: new Set() })
    expect(statusOf(w, 1).attributes('data-status')).toBe('running')
  })
})

describe('WorkBlock: tempo rodando', () => {
  const running = (id: string, ago: number | null) =>
    tool(id, 'Bash', { command: 'sleep 99' }, { result: null, ...(ago === null ? {} : { at: nowSeconds() - ago }) })
  const elapsed = (w: ReturnType<typeof mountBlock>, index: number) => w.findAll('[data-test="work-row"]')[index]!.find('[data-test="work-elapsed"]')

  it('mostra o tempo desde o início, em mono, e avança a cada segundo', async () => {
    const w = mountBlock({ items: [running('a', 12)] })
    expect(elapsed(w, 0).text()).toBe('12 s')
    expect(elapsed(w, 0).classes()).toEqual(expect.arrayContaining(['font-mono', 'tabular-nums']))
    await vi.advanceTimersByTimeAsync(1000)
    expect(elapsed(w, 0).text()).toBe('13 s')
    await vi.advanceTimersByTimeAsync(50_000)
    expect(elapsed(w, 0).text()).toBe('1 min 3 s')
  })

  it('sem hora de início não mostra nada, e o que terminou também não', () => {
    const w = mountBlock({ items: [running('a', null), tool('b', 'Read', {}, { at: nowSeconds() - 30 })] })
    expect(w.findAll('[data-test="work-elapsed"]')).toHaveLength(0)
  })

  it('um relógio só para todas as linhas', () => {
    const spy = spyOnTimer('setInterval')
    mountBlock({ items: [running('a', 5), running('b', 8), running('c', 9)] })
    expect(spy).toHaveBeenCalledTimes(1)
  })

  it('bloco fechado, nada rodando ou sem hora: o relógio não liga', () => {
    const spy = spyOnTimer('setInterval')
    mountBlock({ items: [running('a', 5)], open: false })
    mountBlock({ items: [tool('r', 'Read', {}, { at: nowSeconds() - 3 })] })
    mountBlock({ items: [running('n', null)] })
    expect(spy).not.toHaveBeenCalled()
  })

  it('para o relógio quando a ação termina e quando o bloco é desmontado', async () => {
    const clear = spyOnTimer('clearInterval')
    const w = mountBlock({ items: [running('a', 5)] })
    await w.setProps({ items: [tool('a', 'Bash', { command: 'sleep 99' }, { at: nowSeconds() - 5 })] })
    expect(clear).toHaveBeenCalledTimes(1)
    await w.setProps({ items: [running('a', 5)] })
    w.unmount()
    expect(clear).toHaveBeenCalledTimes(2)
  })

  it('esperando você não mostra o tempo', () => {
    const w = mountBlock({ items: [running('a', 5)], waitingIds: new Set(['tu-a']) })
    expect(w.findAll('[data-test="work-elapsed"]')).toHaveLength(0)
  })
})

describe('WorkBlock: desempenho', () => {
  const edit = (id: string, path: string) => tool(id, 'Edit', { file_path: path, old_string: 'a', new_string: 'b' })
  const callsFor = (item: ToolItem) => spies.toolDiff.mock.calls.filter((call) => toRaw(call[1]) === item.input).length

  it('o diff de uma edição não é recalculado quando só outro item muda', async () => {
    const first = edit('e1', '/p/a.py')
    const second = tool('b', 'Bash', { command: 'make' }, { result: null })
    const w = mountBlock({ items: [first, second] })
    expect(callsFor(first)).toBe(1)
    await w.setProps({ items: [first, tool('b', 'Bash', { command: 'make' }, { result: done })] })
    await w.setProps({ items: [first, tool('b', 'Bash', { command: 'make' }, { result: done }), tool('c', 'Read')] })
    expect(callsFor(first)).toBe(1)
  })

  it('a edição que ganha resultado recalcula o próprio diff', async () => {
    const pending = tool('e1', 'Edit', { file_path: '/p/a.py', old_string: 'a', new_string: 'b' }, { result: null })
    const w = mountBlock({ items: [pending] })
    const before = spies.toolDiff.mock.calls.length
    await w.setProps({ items: [{ ...pending, result: done }] })
    expect(spies.toolDiff.mock.calls.length).toBeGreaterThan(before)
  })
})
