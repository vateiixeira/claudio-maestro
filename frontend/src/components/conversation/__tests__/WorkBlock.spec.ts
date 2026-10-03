import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { ref } from 'vue'
import { SUBAGENT_FOCUS_KEY, type SubagentFocus } from '../../../conversation/subagents'
import WorkBlock from '../WorkBlock.vue'
import type { ToolItem } from '../../../types/conversation'

const done = { content: 'ok', is_error: false, details: null }
const failed = { content: 'deu ruim', is_error: true, details: null }
function tool(id: string, name: string, input: Record<string, unknown> = {}, extra: Partial<ToolItem> = {}): ToolItem {
  return { type: 'tool', id, tool_use_id: `tu-${id}`, name, input, result: done, streaming: false, parent_tool_use_id: null, ...extra }
}

type Props = { items: ToolItem[]; open?: boolean; sessionActive?: boolean }
function mountBlock(props: Props, focus?: ReturnType<typeof ref<SubagentFocus | null>>) {
  return mount(WorkBlock, {
    props: { open: true, ...props },
    global: focus ? { provide: { [SUBAGENT_FOCUS_KEY as symbol]: focus } } : {},
  })
}
const rows = (w: ReturnType<typeof mountBlock>) => w.findAll('[data-test="work-row"] [data-test="work-header"]')

describe('WorkBlock: cabeçalho', () => {
  it('conta as ações e resume por tipo', () => {
    const w = mountBlock({ items: [tool('e', 'Edit', { file_path: '/a' }), tool('b', 'Bash', { command: 'ls' }), tool('x', 'Read', {}, { result: failed })] })
    expect(w.find('[data-test="work-count"]').text()).toBe('3 ações')
    expect(w.find('[data-test="work-count"]').classes()).toContain('cap')
    expect(w.find('[data-test="work-summary"]').text()).toBe('1 edição · 1 comando ok · 1 falhou')
    expect(w.find('[data-test="work-summary"]').classes()).toEqual(expect.arrayContaining(['text-xs', 'text-fg-subtle']))
  })

  it('uma ação só é "1 ação"', () => {
    expect(mountBlock({ items: [tool('r', 'Read')] }).find('[data-test="work-count"]').text()).toBe('1 ação')
  })

  it('o botão do cabeçalho pede para abrir ou fechar e mostra o estado', async () => {
    const w = mountBlock({ items: [tool('r', 'Read'), tool('s', 'Read')], open: false })
    const toggle = w.find('[data-test="work-block-toggle"]')
    expect(toggle.attributes('aria-expanded')).toBe('false')
    expect(toggle.text()).toContain('Ver')
    expect(rows(w)).toHaveLength(0)
    await toggle.trigger('click')
    expect(w.emitted('toggle')).toHaveLength(1)
    await w.setProps({ open: true })
    expect(toggle.attributes('aria-expanded')).toBe('true')
    expect(toggle.text()).toContain('Recolher')
    expect(rows(w)).toHaveLength(2)
  })
})

describe('WorkBlock: linhas', () => {
  it('cada linha é um WorkHeader clicável, fechada quando deu certo', async () => {
    const w = mountBlock({ items: [tool('r', 'Read', { file_path: '/p/a.py' }), tool('b', 'Bash', { command: 'ls -la' })] })
    const [read, bash] = rows(w)
    expect(read!.element.tagName).toBe('BUTTON')
    expect(read!.attributes('data-kind')).toBe('read')
    expect(bash!.attributes('data-kind')).toBe('bash')
    expect(rows(w).map((r) => r.attributes('aria-expanded'))).toEqual(['false', 'false'])
    expect(w.find('[data-test="work-row-body"]').exists()).toBe(false)
    await bash!.trigger('click')
    expect(bash!.attributes('aria-expanded')).toBe('true')
    const body = w.find('[data-test="work-row-body"]')
    expect(body.classes()).toEqual(expect.arrayContaining(['border-t', 'border-line', 'bg-surface']))
    expect(body.find('[data-test="bash-command"]').text()).toContain('ls -la')
    expect(body.find('[data-test="bash-header"]').exists()).toBe(false)
    await bash!.trigger('click')
    expect(w.find('[data-test="work-row-body"]').exists()).toBe(false)
  })

  it('a ação que falhou abre sozinha; o usuário pode fechá-la', async () => {
    const w = mountBlock({ items: [tool('r', 'Read'), tool('b', 'Bash', { command: 'make' }, { result: failed })] })
    const [read, bash] = rows(w)
    expect(read!.attributes('aria-expanded')).toBe('false')
    expect(bash!.attributes('aria-expanded')).toBe('true')
    expect(bash!.find('[data-test="work-status"]').attributes('data-status')).toBe('error')
    expect(w.find('[data-test="tool-error"]').text()).toContain('deu ruim')
    await bash!.trigger('click')
    expect(bash!.attributes('aria-expanded')).toBe('false')
    expect(w.find('[data-test="tool-error"]').exists()).toBe(false)
  })

  it('uma ação que falha depois abre na hora', async () => {
    const running = tool('b', 'Bash', { command: 'make' }, { result: null })
    const w = mountBlock({ items: [running], sessionActive: true })
    expect(rows(w)[0]!.attributes('aria-expanded')).toBe('false')
    await w.setProps({ items: [tool('b', 'Bash', { command: 'make' }, { result: failed })] })
    expect(rows(w)[0]!.attributes('aria-expanded')).toBe('true')
  })

  it('comando fechado com descrição mostra o próprio comando em mono, numa segunda linha', async () => {
    const w = mountBlock({ items: [tool('b', 'Bash', { command: 'pytest -q', description: 'Roda os testes' })] })
    const command = w.find('[data-test="work-command"]')
    expect(command.text()).toBe('pytest -q')
    expect(command.classes()).toEqual(expect.arrayContaining(['font-mono', 'text-fg-muted']))
    await rows(w)[0]!.trigger('click')
    expect(w.find('[data-test="work-command"]').exists()).toBe(false)
  })

  it('comando sem descrição já mostra o comando no título e não repete', () => {
    const w = mountBlock({ items: [tool('b', 'Bash', { command: 'pytest -q' })] })
    expect(w.find('[data-test="work-desc"]').text()).toBe('pytest -q')
    expect(w.find('[data-test="work-command"]').exists()).toBe(false)
  })

  it('edição mostra as linhas somadas e subagente mostra o tipo', () => {
    const sub = { task_id: 't', subagent_type: 'Explore', description: 'achar o bug', status: 'completed' as const, last_activity: null, usage: null, summary: null }
    const w = mountBlock({
      items: [tool('e', 'Edit', { file_path: '/p/a.py', old_string: 'a', new_string: 'b\nc' }), tool('a', 'Agent', {}, { subagent: sub })],
    })
    const [edit, agent] = rows(w)
    expect(edit!.text()).toContain('+2')
    expect(edit!.text()).toContain('−1')
    expect(agent!.find('[data-test="work-tag"]').text()).toBe('Explore')
    expect(agent!.text()).toContain('achar o bug')
  })
})

describe('WorkBlock: card aberto de cada tipo', () => {
  const sub = { task_id: 't', subagent_type: 'Explore', description: 'achar o bug', status: 'completed' as const, last_activity: null, usage: null, summary: 'achei' }
  it.each([
    ['leitura', tool('r', 'Read', { file_path: '/p/a.py' }, { result: { ...done, content: 'conteúdo do arquivo' } }), 'conteúdo do arquivo'],
    ['busca', tool('g', 'Grep', { pattern: 'foo' }, { result: { ...done, content: '/p/a.py:1' } }), '/p/a.py:1'],
    ['edição', tool('e', 'Edit', { file_path: '/p/a.py', old_string: 'velho', new_string: 'novo' }), 'novo'],
    ['ferramenta', tool('m', 'mcp__s__t', { x: 1 }, { result: { ...done, content: 'resposta' } }), 'resposta'],
    ['subagente', tool('a', 'Agent', { description: 'd' }, { subagent: sub }), 'achei'],
  ])('%s: mostra só o corpo, o cabeçalho é a linha', async (_name, item, text) => {
    const w = mountBlock({ items: [item] })
    await rows(w)[0]!.trigger('click')
    const body = w.find('[data-test="work-row-body"]')
    expect(body.text()).toContain(text)
    expect(body.find('[data-test="work-header"]').exists()).toBe(false)
    expect(w.findAll('[data-test="work-header"]')).toHaveLength(1)
  })
})

describe('WorkBlock: atividade', () => {
  const running = tool('b', 'Bash', { command: 'pytest -q' }, { result: null })

  it('fechado e rodando, uma linha mono em âmbar diz o que acontece', () => {
    const w = mountBlock({ items: [tool('r', 'Read', { file_path: '/p/a.py' }), running], open: false, sessionActive: true })
    const line = w.find('[data-test="work-activity"]')
    expect(line.text()).toBe('Comando · pytest -q')
    expect(line.classes()).toEqual(expect.arrayContaining(['font-mono', 'text-[0.6875rem]', 'text-secondary-soft']))
  })

  it('não aparece aberto, nem quando nada roda', async () => {
    const w = mountBlock({ items: [running], open: true, sessionActive: true })
    expect(w.find('[data-test="work-activity"]').exists()).toBe(false)
    await w.setProps({ open: false })
    expect(w.find('[data-test="work-activity"]').exists()).toBe(true)
    await w.setProps({ sessionActive: false })
    expect(w.find('[data-test="work-activity"]').exists()).toBe(false)
    expect(mountBlock({ items: [tool('r', 'Read')], open: false, sessionActive: true }).find('[data-test="work-activity"]').exists()).toBe(false)
  })
})

describe('WorkBlock: pedido para chegar a uma ação', () => {
  it('abre o bloco e a linha da ação (ou do subagente que a guarda)', async () => {
    const focus = ref<SubagentFocus | null>(null)
    const w = mountBlock({ items: [tool('r', 'Read'), tool('ag', 'Agent')], open: false }, focus)
    focus.value = { id: 'inner', path: ['inner', 'ag'] }
    await w.vm.$nextTick()
    expect(w.emitted('toggle')).toHaveLength(1)
    await w.setProps({ open: true })
    expect(rows(w).map((r) => r.attributes('aria-expanded'))).toEqual(['false', 'true'])
  })

  it('não mexe quando a ação é de outro bloco', async () => {
    const focus = ref<SubagentFocus | null>(null)
    const w = mountBlock({ items: [tool('r', 'Read')], open: false }, focus)
    focus.value = { id: 'z', path: ['z'] }
    await w.vm.$nextTick()
    expect(w.emitted('toggle')).toBeUndefined()
  })
})
