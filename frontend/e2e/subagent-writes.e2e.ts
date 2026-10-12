import { expect, test } from './fixtures'

// The seeded server cannot run an agent, and a recorded history has no subagent actions (the CLI
// keeps them in other files), so this spec adds a subagent to the snapshot of a seeded conversation.
const done = { content: 'ok', is_error: false, details: null }
const subagentItems = [
  {
    type: 'tool', id: 'sa-agent', tool_use_id: 'tu-sa-agent', name: 'Agent',
    input: { subagent_type: 'implementer', description: 'Criar o módulo novo' },
    result: done, streaming: false, parent_tool_use_id: null,
    subagent: {
      task_id: 't1', subagent_type: 'implementer', description: 'Criar o módulo novo',
      status: 'completed', last_activity: null, usage: null, summary: 'Módulo criado.',
    },
  },
  {
    type: 'tool', id: 'sa-read', tool_use_id: 'tu-sa-read', name: 'Read',
    input: { file_path: '/tmp/projeto/leia-me.md' }, result: done, streaming: false, parent_tool_use_id: 'tu-sa-agent',
  },
  {
    type: 'tool', id: 'sa-write', tool_use_id: 'tu-sa-write', name: 'Write',
    input: { file_path: '/tmp/projeto/modulo_novo.py', content: 'print("oi")\n' }, result: done, streaming: false,
    parent_tool_use_id: 'tu-sa-agent',
  },
]

test('a escrita de um subagente aparece na conversa com o nome dele e continua no cartão', async ({ page }) => {
  await page.route(/\/api\/sessions\/[0-9a-f-]+$/, async (route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    const response = await route.fetch()
    const snapshot = await response.json()
    snapshot.items = [...snapshot.items, ...subagentItems]
    await route.fulfill({ response, json: snapshot })
  })
  await page.goto('/sessions')
  await page.getByText('Explique a estrutura do projeto').first().click()

  // The subagent and its write are the actions of one work block, which starts closed.
  const block = page.getByTestId('work-block')
  await expect(block.getByTestId('work-count')).toHaveText('2 ações')
  await block.getByTestId('work-block-toggle').click()
  const rows = block.getByTestId('work-row')
  await expect(rows).toHaveCount(2)
  await expect(rows.nth(1).getByTestId('work-tag')).toHaveText('implementer')
  await expect(rows.nth(1).getByTestId('work-desc')).toHaveText('/tmp/projeto/modulo_novo.py')

  // The card still lists every action of the subagent, the write included.
  await rows.nth(0).getByTestId('work-header').click()
  const card = page.getByTestId('subagent-card')
  await expect(card.getByTestId('subagent-toggle')).toContainText('Ações (2)')
  await card.getByTestId('subagent-toggle').click()
  const children = card.getByTestId('subagent-children')
  await expect(children.getByText('modulo_novo.py')).toBeVisible()
  await expect(children.getByText('leia-me.md')).toBeVisible()

  // The write is counted once in the footer of the turn.
  await expect(page.getByTestId('turn-end-summary').first()).toContainText('3 ações · 1 arquivo alterado')
})

// A richer conversation: text of the main agent between writes, several writes in a row, a nested
// subagent, and writes of the main agent itself (which get no chip).
const tool = (id: string, name: string, input: Record<string, unknown>, parent: string | null, extra: Record<string, unknown> = {}) => ({
  type: 'tool', id, tool_use_id: `tu-${id}`, name, input, result: done, streaming: false,
  parent_tool_use_id: parent === null ? null : `tu-${parent}`, ...extra,
})
const subagent = (type: string, description: string) => ({
  task_id: `task-${type}`, subagent_type: type, description, status: 'completed', last_activity: null, usage: null, summary: 'Pronto.',
})
const text = (id: string, body: string) => ({ type: 'text', id, text: body, streaming: false, parent_tool_use_id: null, at: 1791829230 })

const richItems = [
  tool('m-edit', 'Edit', { file_path: '/tmp/projeto/principal.py', old_string: 'a = 1', new_string: 'a = 2' }, null),
  tool('ag-a', 'Agent', { subagent_type: 'implementer', description: 'Implementar' }, null, { subagent: subagent('implementer', 'Implementar') }),
  tool('a-read', 'Read', { file_path: '/tmp/projeto/leia-me.md' }, 'ag-a'),
  tool('a-bash', 'Bash', { command: 'ls -la', description: 'Listar' }, 'ag-a'),
  tool('a-write', 'Write', { file_path: '/tmp/projeto/um.py', content: 'x = 1\n' }, 'ag-a'),
  text('t-mid', 'Texto do agente principal no meio.'),
  tool('a-edit', 'Edit', { file_path: '/tmp/projeto/dois.py', old_string: 'velho', new_string: 'novo' }, 'ag-a'),
  tool('a-multi', 'MultiEdit', { file_path: '/tmp/projeto/tres.py', edits: [{ old_string: 'p', new_string: 'q' }] }, 'ag-a'),
  tool('ag-b', 'Agent', { subagent_type: 'reviewer', description: 'Revisar' }, 'ag-a', { subagent: subagent('reviewer', 'Revisar') }),
  tool('b-write', 'Write', { file_path: '/tmp/projeto/aninhado.py', content: 'y = 2\n' }, 'ag-b'),
  tool('m-write', 'Write', { file_path: '/tmp/projeto/final.py', content: 'z = 3\n' }, null),
]

test('várias escritas de subagentes, aninhado e texto no meio', async ({ page }) => {
  await page.route(/\/api\/sessions\/[0-9a-f-]+$/, async (route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    const response = await route.fetch()
    const snapshot = await response.json()
    snapshot.items = [...snapshot.items, ...richItems]
    await route.fulfill({ response, json: snapshot })
  })
  await page.goto('/sessions')
  await page.getByText('Explique a estrutura do projeto').first().click()

  const blocks = page.getByTestId('work-block')
  await expect(blocks).toHaveCount(2)
  await expect(blocks.nth(0).getByTestId('work-count')).toHaveText('3 ações')
  await expect(blocks.nth(1).getByTestId('work-count')).toHaveText('4 ações')

  // Order of arrival: main edit, the subagent card, its first write; then the main agent's text; then the rest.
  await blocks.nth(0).getByTestId('work-block-toggle').click()
  await blocks.nth(1).getByTestId('work-block-toggle').click()
  const first = blocks.nth(0).getByTestId('work-row')
  await expect(first).toHaveCount(3)
  await expect(first.nth(0).getByTestId('work-desc')).toHaveText('/tmp/projeto/principal.py')
  await expect(first.nth(0).getByTestId('work-tag')).toHaveCount(0)
  await expect(first.nth(2).getByTestId('work-tag')).toHaveText('implementer')
  await expect(first.nth(2).getByTestId('work-desc')).toHaveText('/tmp/projeto/um.py')

  const second = blocks.nth(1).getByTestId('work-row')
  await expect(second).toHaveCount(4)
  await expect(second.nth(0).getByTestId('work-tag')).toHaveText('implementer')
  await expect(second.nth(0).getByTestId('work-desc')).toHaveText('/tmp/projeto/dois.py')
  await expect(second.nth(1).getByTestId('work-tag')).toHaveText('implementer')
  await expect(second.nth(1).getByTestId('work-desc')).toHaveText('/tmp/projeto/tres.py')
  await expect(second.nth(2).getByTestId('work-tag')).toHaveText('reviewer')
  await expect(second.nth(2).getByTestId('work-desc')).toHaveText('/tmp/projeto/aninhado.py')
  // The main agent's own write has no chip.
  await expect(second.nth(3).getByTestId('work-desc')).toHaveText('/tmp/projeto/final.py')
  await expect(second.nth(3).getByTestId('work-tag')).toHaveCount(0)

  // The text of the main agent stays between the two blocks.
  const thread = page.getByTestId('turn').getByText('Texto do agente principal no meio.')
  const textBox = await thread.boundingBox()
  const firstBox = await blocks.nth(0).boundingBox()
  const secondBox = await blocks.nth(1).boundingBox()
  expect(firstBox!.y + firstBox!.height).toBeLessThanOrEqual(textBox!.y)
  expect(textBox!.y + textBox!.height).toBeLessThanOrEqual(secondBox!.y)

  // The write of a subagent expands to its diff like any other write.
  await second.nth(0).getByTestId('work-header').click()
  await expect(blocks.nth(1).getByText('velho')).toBeVisible()
  await expect(blocks.nth(1).getByText('novo')).toBeVisible()

  // Each write counts once in the footer: 10 actions (two subagents, a read and a command included), 6 files.
  await expect(page.getByTestId('turn-end-summary').first()).toContainText('10 ações · 6 arquivos alterados')

  // The card of the main subagent lists all its actions, nested subagent's write included in its own card.
  await first.nth(1).getByTestId('work-header').click()
  const card = page.getByTestId('subagent-card').first()
  await expect(card.getByTestId('subagent-toggle').first()).toContainText('Ações (6)')
  await card.getByTestId('subagent-toggle').first().click()
  const children = card.getByTestId('subagent-children').first()
  await expect(children.getByText('um.py')).toBeVisible()
  await expect(children.getByText('dois.py')).toBeVisible()
  await expect(children.getByText('tres.py')).toBeVisible()
  await expect(children.getByText('leia-me.md')).toBeVisible()
  // The nested subagent keeps its own write in its own card.
  const nested = children.getByTestId('subagent-card')
  await expect(nested.getByTestId('subagent-toggle')).toContainText('Ações (1)')
  await nested.getByTestId('subagent-toggle').click()
  await expect(nested.getByTestId('subagent-children').getByText('aninhado.py')).toBeVisible()
})
