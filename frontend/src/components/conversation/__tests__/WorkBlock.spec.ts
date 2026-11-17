import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { ref } from 'vue'
import { SUBAGENT_FOCUS_KEY, type SubagentFocus } from '../../../conversation/subagents'
import WorkBlock from '../WorkBlock.vue'
import Collapse from '../../Collapse.vue'
import type { ToolItem } from '../../../types/conversation'

const done = { content: 'ok', is_error: false, details: null }
const failed = { content: 'deu ruim', is_error: true, details: null }
function tool(id: string, name: string, input: Record<string, unknown> = {}, extra: Partial<ToolItem> = {}): ToolItem {
  return { type: 'tool', id, tool_use_id: `tu-${id}`, name, input, result: done, streaming: false, parent_tool_use_id: null, ...extra }
}

type Props = { items: ToolItem[]; open?: boolean; sessionActive?: boolean; endAt?: number | null }
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
    expect(w.find('[data-test="work-count"]').classes()).toContain('sr-only')
    expect(w.classes()).not.toContain('border')
    expect(w.find('[data-test="work-summary"]').text()).toBe('Executou 1 comando, fez 1 leitura, editou a')
    expect(w.find('[data-test="work-failed"]').text()).toBe('1 falhou')
    expect(w.find('[data-test="work-summary"]').classes()).toContain('truncate')
  })

  it('uma ação só é "1 ação"', () => {
    expect(mountBlock({ items: [tool('r', 'Read')] }).find('[data-test="work-count"]').text()).toBe('1 ação')
  })

  it('o botão do cabeçalho pede para abrir ou fechar e mostra o estado', async () => {
    const w = mountBlock({ items: [tool('r', 'Read'), tool('s', 'Read')], open: false })
    const toggle = w.find('[data-test="work-block-toggle"]')
    expect(toggle.attributes('aria-expanded')).toBe('false')
    expect(toggle.attributes('aria-label')).toContain('Ver')
    expect(rows(w)).toHaveLength(0)
    await toggle.trigger('click')
    expect(w.emitted('toggle')).toHaveLength(1)
    await w.setProps({ open: true })
    expect(toggle.attributes('aria-expanded')).toBe('true')
    expect(toggle.attributes('aria-label')).toContain('Recolher')
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

describe('WorkBlock: modelo do subagente', () => {
  it('a linha do subagente mostra o modelo ao lado do tipo', () => {
    const sub = { task_id: 't', subagent_type: 'Explore', description: 'achar', status: 'completed' as const, last_activity: null, usage: null, summary: null, model: 'claude-haiku-4-5-20251001' }
    const w = mountBlock({ items: [tool('a', 'Agent', {}, { subagent: sub }), tool('r', 'Read', { file_path: '/p/a.py' })] })
    const [agent, read] = rows(w)
    expect(agent!.find('[data-test="model-chip"]').text()).toBe('Haiku 4.5')
    expect(read!.find('[data-test="model-chip"]').exists()).toBe(false)
  })
})

describe('WorkBlock: modelo "inherit"', () => {
  it('a linha do subagente não mostra chip para o modelo "inherit" da chamada', () => {
    const w = mountBlock({ items: [tool('a', 'Agent', { model: 'inherit' }), tool('r', 'Read', { file_path: '/p/a.py' })] })
    expect(w.find('[data-test="model-chip"]').exists()).toBe(false)
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
  const running = tool('b', 'Bash', { command: 'pytest -q', description: 'Rodar os testes' }, { result: null })

  it('a atividade ocupa o cabeçalho, sem uma segunda linha', async () => {
    const w = mountBlock({ items: [running], open: false, sessionActive: true })
    const header = w.find('[data-test="work-summary"]')
    expect(header.text()).toBe('Rodar os testes')
    expect(header.classes()).toContain('text-secondary-soft')
    expect(w.find('[data-test="work-activity"]').exists()).toBe(false)
    await w.setProps({ open: true })
    expect(header.text()).toBe('Rodar os testes')
    await w.setProps({ items: [tool('b', 'Bash', running.input)] })
    expect(w.find('[data-test="work-summary"]').text()).toBe('Executou 1 comando')
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

describe('WorkBlock: animações', () => {
  it('o resumo só anima quando o texto muda, não ao montar', async () => {
    const w = mountBlock({ items: [tool('b', 'Bash', { command: 'ls' }, { result: null })], sessionActive: true })
    expect(w.find('[data-test="work-summary"]').classes()).not.toContain('animate-enter')
    await w.setProps({ items: [tool('b', 'Bash', { command: 'ls' })] })
    expect(w.find('[data-test="work-summary"]').text()).toBe('Executou 1 comando')
    expect(w.find('[data-test="work-summary"]').classes()).toContain('animate-enter')
    expect(w.find('[data-test="work-summary"]').classes()).toContain('[animation-duration:var(--motion-state)]')
  })

  it('a caixa e o corpo de cada linha abrem e fecham dentro de um Collapse, com aria-expanded certo', async () => {
    const w = mountBlock({ items: [tool('b', 'Bash', { command: 'ls' })], open: false })
    const collapses = () => w.findAllComponents(Collapse).map((c) => c.props('open'))
    expect(collapses()).toEqual([false])
    await w.setProps({ open: true })
    expect(collapses()).toEqual([true, false])
    await rows(w)[0]!.trigger('click')
    expect(collapses()).toEqual([true, true])
    expect(rows(w)[0]!.attributes('aria-expanded')).toBe('true')
  })

  it('o chevron do cabeçalho gira no tempo do movimento do app', () => {
    const w = mountBlock({ items: [tool('r', 'Read')], open: true })
    const chevron = w.find('[data-test="work-block-toggle"] svg')
    expect(chevron.classes()).toEqual(expect.arrayContaining(['duration-(--motion-enter)', 'ease-(--ease-maestro)']))
  })
})

describe('WorkBlock: grupos', () => {
  const items = () => [
    tool('b1', 'Bash', { command: 'cd /home/ana/dev/a && ls', description: 'Listar' }),
    tool('b2', 'Bash', { command: 'cd /home/ana/dev/a && pwd' }),
    tool('b3', 'Bash', { command: 'cd /home/ana/dev/b && ls' }),
    tool('q', 'mcp__banco__query', { query: 'select 1' }),
  ]

  it('junta as ações seguidas do mesmo tipo e da mesma pasta, e mostra pastas', () => {
    const w = mountBlock({ items: items() })
    const groups = w.findAll('[data-test="work-group"]')
    expect(groups).toHaveLength(3)
    expect(groups[0]!.attributes('data-kind')).toBe('bash')
    expect(groups[0]!.find('[data-test="work-group-label"]').text()).toBe('Comandos')
    expect(groups[0]!.find('[data-test="work-group-where"]').text()).toBe('em ~/dev/a')
    expect(groups[0]!.find('[data-test="work-group-count"]').text()).toBe('2')
    expect(groups[2]!.find('[data-test="work-group-label"]').text()).toBe('Ferramenta')
    expect(groups[2]!.find('[data-test="work-group-where"]').text()).toBe('banco · query')
    expect(w.findAll('[data-test="work-row"]')).toHaveLength(4)
    for (const header of rows(w)) expect(header.find('[data-test="work-slot"]').exists()).toBe(true)
    expect(w.find('[data-test="work-folders"]').text()).toBe('em 2 pastas')
  })

  it('o título do grupo usa o tom do tipo', () => {
    const w = mountBlock({ items: items() })
    const head = w.find('[data-test="work-group"] [data-test="work-group-head"]')
    expect(head.classes()).toContain('text-type-command')
  })

  it('com uma pasta só, não diz quantas', () => {
    const w = mountBlock({ items: [tool('b1', 'Bash', { command: 'cd /home/ana/dev/a && ls' }), tool('b2', 'Bash', { command: 'cd /home/ana/dev/a && pwd' })] })
    expect(w.find('[data-test="work-folders"]').exists()).toBe(false)
  })

  it('o comando sem o cd aparece na linha', () => {
    const w = mountBlock({ items: [tool('b1', 'Bash', { command: 'cd /home/ana/dev/a && ls -la', description: 'Listar' })] })
    expect(rows(w)[0]!.find('[data-test="work-command"]').text()).toBe('ls -la')
  })
})

describe('WorkBlock: falha e nova tentativa', () => {
  const sqlFail = () => tool('f', 'mcp__banco__query', { query: 'select x' }, { result: { content: 'column x does not exist\ndetalhe', is_error: true, details: null } })
  const sqlOk = () => tool('o', 'mcp__banco__query', { query: 'select y' })

  it('resume a falha refeita, abre a linha com a faixa Erro e marca a nova tentativa', () => {
    const w = mountBlock({ items: [sqlFail(), sqlOk()] })
    expect(w.find('[data-test="work-failed"]').text()).toBe('1 falhou, refeita em seguida')
    expect(w.find('[data-test="work-summary"]').classes()).not.toContain('text-diff-del-fg')
    const [first, second] = rows(w)
    expect(first!.attributes('aria-expanded')).toBe('true')
    expect(second!.find('[data-test="work-retry"]').text()).toBe('Nova tentativa')
    expect(first!.find('[data-test="work-retry"]').exists()).toBe(false)
    const body = w.find('[data-test="work-row-body"]')
    expect(body.element.firstElementChild!.getAttribute('data-test')).toBe('work-error')
    expect(body.find('[data-test="work-error-text"]').text()).toBe('column x does not exist')
    expect(w.find('[data-test="work-retry-note"]').text()).toBe('A tentativa seguinte passou.')
  })

  it('sem nova tentativa não promete nada', () => {
    const w = mountBlock({ items: [sqlFail(), tool('r', 'Read')] })
    expect(w.find('[data-test="work-failed"]').text()).toBe('1 falhou')
    expect(w.find('[data-test="work-retry"]').exists()).toBe(false)
    expect(w.find('[data-test="work-retry-note"]').exists()).toBe(false)
    expect(w.find('[data-test="work-error"]').exists()).toBe(true)
  })

  it('sem falha não mostra o aviso', () => {
    const w = mountBlock({ items: [tool('r', 'Read')] })
    expect(w.find('[data-test="work-failed"]').exists()).toBe(false)
  })

  it('o botão de copiar o erro copia o texto inteiro', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
    const w = mountBlock({ items: [sqlFail(), sqlOk()] })
    const copy = w.find('[data-test="work-error-copy"]')
    expect(copy.attributes('aria-label')).toBe('Copiar erro')
    await copy.trigger('click')
    expect(writeText).toHaveBeenCalledWith('column x does not exist\ndetalhe')
  })

  it('o botão do cabeçalho fechado diz a falha', () => {
    const w = mountBlock({ items: [sqlFail(), sqlOk()], open: false })
    expect(w.find('[data-test="work-block-toggle"]').attributes('aria-label')).toBe('Ver 2 ações: Usou 2 ferramentas · 1 falhou, refeita em seguida')
  })
})

describe('WorkBlock: frase do cabeçalho', () => {
  const summary = (w: ReturnType<typeof mountBlock>) => w.find('[data-test="work-summary"]')
  it('aberta fica em destaque, fechada discreta, rodando laranja', () => {
    const open = mountBlock({ items: [tool('r', 'Read')], open: true })
    expect(summary(open).classes()).toEqual(expect.arrayContaining(['font-medium', 'text-fg']))
    const closed = mountBlock({ items: [tool('r', 'Read')], open: false })
    expect(summary(closed).classes()).toContain('text-fg-muted')
    const live = mountBlock({ items: [tool('b', 'Bash', { command: 'ls' }, { result: null })], open: false, sessionActive: true })
    expect(summary(live).classes()).toContain('text-secondary-soft')
  })
})

describe('WorkBlock: duração', () => {
  it('mostra do início da primeira ação até o fim, arredondado', () => {
    const w = mountBlock({ items: [tool('a', 'Read', {}, { at: 100 }), tool('b', 'Read', {}, { at: 120 })], endAt: 138.4 })
    expect(w.find('[data-test="work-span"]').text()).toBe('38 s')
  })

  it('sem fim e sem nada rodando, não mostra', () => {
    const w = mountBlock({ items: [tool('a', 'Read', {}, { at: 100 })] })
    expect(w.find('[data-test="work-span"]').exists()).toBe(false)
  })

  it('sem horário de início (histórico antigo), não mostra nem liga o relógio', () => {
    const w = mountBlock({ items: [tool('a', 'Read'), tool('b', 'Read')], endAt: 138 })
    expect(w.find('[data-test="work-span"]').exists()).toBe(false)
  })
})

describe('WorkBlock: o que o bloco produziu', () => {
  const edit = tool('e', 'Edit', { file_path: '/p/a.md', old_string: '', new_string: Array.from({ length: 41 }, (_, i) => `l${i}`).join('\n') })
  const sub = { task_id: 't', subagent_type: 'Explore', description: 'Tarefa 1 · tela inicial', status: 'completed' as const, last_activity: null, usage: { total_tokens: 31000, duration_ms: 228000 }, summary: 'ok' }
  const agent = tool('a', 'Agent', {}, { subagent: sub })

  it('fechado, mostra o arquivo e o subagente', () => {
    const w = mountBlock({ items: [edit, agent], open: false })
    const file = w.find('[data-test="work-file-chip"]')
    expect(file.attributes('data-path')).toBe('/p/a.md')
    expect(file.text()).toContain('a.md')
    expect(file.text()).toContain('+41')
    expect(file.text()).not.toContain('−')
    const chip = w.find('[data-test="work-agent-chip"]')
    expect(chip.attributes('data-status')).toBe('completed')
    expect(chip.text()).toContain('Tarefa 1 · tela inicial')
    expect(chip.find('[data-test="work-agent-meta"]').text()).toBe('3 min 48 s · 31 mil tokens')
  })

  it('clicar no subagente abre o bloco e a linha dele', async () => {
    const w = mountBlock({ items: [edit, agent], open: false })
    await w.find('[data-test="work-agent-chip"]').trigger('click')
    expect(w.emitted('toggle')).toHaveLength(1)
    await w.setProps({ open: true })
    const [, agentRow] = rows(w)
    expect(agentRow!.attributes('aria-expanded')).toBe('true')
    expect(w.find('[data-test="work-row-body"]').exists()).toBe(true)
  })

  it('aberto, os chips não aparecem', () => {
    const w = mountBlock({ items: [edit, agent], open: true })
    expect(w.find('[data-test="work-artifacts"]').exists()).toBe(false)
  })

  it('a tira de imagens continua nos dois estados', () => {
    const img = tool('i', 'Read', { file_path: '/p/a.png' }, { result: { content: [{ type: 'image', omitted: true, index: 0, media_type: 'image/png', size: 10 }], is_error: false, details: null } })
    expect(mountBlock({ items: [img], open: false }).find('[data-test="tool-image-strip"]').exists()).toBe(true)
    expect(mountBlock({ items: [img], open: true }).find('[data-test="tool-image-strip"]').exists()).toBe(true)
  })

  it('sem arquivo nem subagente, não há faixa', () => {
    expect(mountBlock({ items: [tool('r', 'Read')], open: false }).find('[data-test="work-artifacts"]').exists()).toBe(false)
  })
})
