import type { Page } from '@playwright/test'
import { expect, test } from './fixtures'

// The seeded server cannot run an agent, so the running turn is staged: the snapshot of a seeded
// conversation is rewritten (it becomes a running session) and the socket is replaced by one the
// spec writes to, like the backend would. `server` plays the backend: it keeps the state that a
// reload of the page would read back.

type Item = Record<string, unknown>
const ok = { content: 'ok', is_error: false, details: null }
const nowSeconds = () => Math.floor(Date.now() / 1000)

const tool = (id: string, name: string, input: Record<string, unknown>, extra: Item = {}): Item => ({
  type: 'tool', id, tool_use_id: `tu-${id}`, name, input, result: ok, streaming: false, parent_tool_use_id: null, ...extra,
})
const running = (id: string, name: string, input: Record<string, unknown>) => tool(id, name, input, { result: null, streaming: true })
const todos = (id: string, list: Array<[string, string]>) =>
  tool(id, 'TodoWrite', {
    todos: list.map(([content, status]) => ({ content, status, activeForm: content })),
  })

async function stageRunningTurn(page: Page, options: { startedAt?: number | null; tokens?: number } = {}) {
  const server = {
    seq: 0,
    state: 'running',
    items: [] as Item[],
    prompts: [] as Item[],
    startedAt: options.startedAt === undefined ? nowSeconds() - 65 : options.startedAt,
    tokens: options.tokens ?? 0,
  }
  let socket: { send(message: string): void } | null = null
  await page.routeWebSocket(/\/ws$/, (ws) => {
    socket = ws
  })
  await page.route(/\/api\/sessions\/[0-9a-f-]+$/, async (route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    const response = await route.fetch()
    const snapshot = await response.json()
    await route.fulfill({
      response,
      json: {
        ...snapshot,
        state: server.state,
        seq: server.seq,
        items: [...snapshot.items, ...server.items],
        prompts: server.prompts,
        turn_output_tokens: server.tokens,
        turn_started_at: server.state === 'running' ? server.startedAt : null,
      },
    })
  })
  await page.goto('/sessions')
  await page.getByText('Explique a estrutura do projeto').first().click()
  const sessionId = page.url().match(/[0-9a-f]{8}-[0-9a-f-]{27}/)?.[0] ?? ''
  const push = async (type: string, data: Item) => {
    await expect.poll(() => socket !== null).toBe(true)
    server.seq += 1
    socket!.send(JSON.stringify({ session_id: sessionId, seq: server.seq, type, data }))
  }
  return {
    server,
    /** Items the backend upserts; they stay in the snapshot too. */
    async upsert(item: Item) {
      const index = server.items.findIndex((i) => i.id === item.id)
      if (index >= 0) server.items[index] = item
      else server.items.push(item)
      await push('item.upsert', item)
    },
    async tokens(count: number) {
      server.tokens = count
      await push('turn.tokens', { output_tokens: count })
    },
    async prompt(prompt: Item) {
      server.prompts.push(prompt)
      await push('prompt.request', prompt)
    },
    async finish() {
      server.state = 'idle'
      await push('session.state', { state: 'idle', error: null })
    },
  }
}

const progress = (page: Page) => page.getByTestId('turn-progress')
const marks = (page: Page) => page.getByTestId('turn-task').evaluateAll((els) => els.map((el) => el.getAttribute('data-status')))

test('a lista de tarefas do turno em andamento se atualiza no lugar e não vira entrada do trilho', async ({ page }) => {
  const turn = await stageRunningTurn(page)
  await turn.upsert(running('r1', 'Read', { file_path: '/tmp/projeto/leia-me.md' }))
  await turn.upsert(todos('todo-1', [['Mapear o código', 'in_progress'], ['Escrever o teste', 'pending'], ['Rodar a suíte', 'pending']]))

  const card = progress(page).getByTestId('turn-tasks')
  await expect(card).toBeVisible()
  await expect(card.getByTestId('turn-tasks-count')).toHaveText('0 de 3')
  expect(await marks(page)).toEqual(['in_progress', 'pending', 'pending'])

  // The same list is rewritten by the next TodoWrite: it updates in place, there is still one card.
  await turn.upsert(todos('todo-2', [['Mapear o código', 'completed'], ['Escrever o teste', 'in_progress'], ['Rodar a suíte', 'pending']]))
  await expect(card.getByTestId('turn-tasks-count')).toHaveText('1 de 3')
  expect(await marks(page)).toEqual(['completed', 'in_progress', 'pending'])
  await expect(page.getByTestId('turn-tasks')).toHaveCount(1)

  await turn.upsert(todos('todo-3', [['Mapear o código', 'completed'], ['Escrever o teste', 'completed'], ['Rodar a suíte', 'in_progress']]))
  await expect(card.getByTestId('turn-tasks-count')).toHaveText('2 de 3')
  await expect(card.getByTestId('turn-task').nth(2)).toHaveAttribute('data-status', 'in_progress')

  // The task tools are neither rail entries nor actions: only the Read is counted.
  await expect(page.getByTestId('work-block')).toHaveCount(1)
  await expect(page.getByTestId('work-count')).toHaveText('1 ação')
  await expect(page.getByTestId('work-block').getByText('TodoWrite')).toHaveCount(0)
})

test('a linha viva mostra a ação, o tempo que passa e os tokens quando chegam', async ({ page }) => {
  const turn = await stageRunningTurn(page)
  const live = page.getByTestId('turn-live')

  // Only thinking, tokens unknown: no tokens in the line.
  await expect(live.getByTestId('turn-live-activity')).toHaveText('Pensando')
  await expect(live.getByTestId('turn-live-dot')).toHaveCount(3)
  await expect(live.getByTestId('turn-live-meta')).toHaveText(/^ · 1 min \d+ s$/)
  const first = await live.getByTestId('turn-live-meta').innerText()
  await expect.poll(() => live.getByTestId('turn-live-meta').innerText()).not.toBe(first)

  // An action runs.
  await turn.upsert(running('b1', 'Bash', { command: 'pnpm test', description: 'Rodar os testes' }))
  await expect(live.getByTestId('turn-live-activity')).not.toHaveText(/^(Pensando|Escrevendo|esperando você)$/)
  await expect(live.getByTestId('turn-live-activity')).toContainText('Rodar os testes')

  // The tokens arrive.
  await turn.tokens(1600)
  await expect(live.getByTestId('turn-live-meta')).toContainText('1,6 mil tokens')
  await expect(live.getByTestId('turn-live-meta')).toContainText('1 min')

  // The action ends and the reply is written.
  await turn.upsert(tool('b1', 'Bash', { command: 'pnpm test', description: 'Rodar os testes' }))
  await turn.upsert({ type: 'text', id: 'txt-1', text: 'Estou escrevendo', streaming: true, parent_tool_use_id: null, at: nowSeconds() })
  await expect(live.getByTestId('turn-live-activity')).toHaveText('Escrevendo')
})

test('um pedido pendente troca a linha viva por "esperando você"', async ({ page }) => {
  const turn = await stageRunningTurn(page)
  await turn.upsert(running('w1', 'Write', { file_path: '/tmp/projeto/novo.py', content: 'x = 1\n' }))
  await turn.prompt({
    prompt_id: 'p1', tool_name: 'Write', tool_use_id: 'tu-w1', can_always: true,
    input: { file_path: '/tmp/projeto/novo.py', content: 'x = 1\n' },
  })
  await expect(page.getByTestId('permission-card')).toBeVisible()
  await expect(page.getByTestId('turn-live-activity')).toHaveText('esperando você')
})

test('ao terminar, o cartão fica apagado acima do "Concluído" e a linha viva some', async ({ page }) => {
  const turn = await stageRunningTurn(page)
  await turn.upsert(todos('todo-1', [['Mapear o código', 'completed'], ['Rodar a suíte', 'pending']]))
  await expect(page.getByTestId('turn-live')).toBeVisible()

  await turn.finish()
  await expect(page.getByTestId('turn-live')).toHaveCount(0)
  await expect(page.getByTestId('turn-progress')).toHaveCount(0)
  const card = page.getByTestId('turn-tasks')
  await expect(card).toHaveCount(1)
  await expect(card).toHaveAttribute('data-muted', 'true')
  await expect(page.getByTestId('turn-end-label')).toHaveText('Concluído')
  // The card sits above the "Concluído" line.
  const cardBox = (await card.boundingBox())!
  const endBox = (await page.getByTestId('turn-end').boundingBox())!
  expect(cardBox.y + cardBox.height).toBeLessThanOrEqual(endBox.y)
  // Nothing spins in a finished turn.
  await expect(card.locator('.animate-spin')).toHaveCount(0)
})

test('recarregar a página no meio do turno mantém a lista, o tempo e os tokens', async ({ page }) => {
  const turn = await stageRunningTurn(page)
  await turn.upsert(todos('todo-1', [['Mapear o código', 'completed'], ['Escrever o teste', 'in_progress']]))
  await turn.tokens(2400)
  const live = page.getByTestId('turn-live')
  await expect(live.getByTestId('turn-live-meta')).toContainText('2,4 mil tokens')

  await page.reload()
  await expect(page.getByTestId('turn-tasks-count')).toHaveText('1 de 2')
  expect(await marks(page)).toEqual(['completed', 'in_progress'])
  await expect(live.getByTestId('turn-live-meta')).toContainText('2,4 mil tokens')
  // The time keeps counting from the start of the turn (65 s before the stage), not from zero.
  await expect(live.getByTestId('turn-live-meta')).toHaveText(/ · 1 min \d+ s · /)
})

test('um turno só com TodoWrite não deixa trilho vazio', async ({ page }) => {
  const turn = await stageRunningTurn(page)
  await turn.upsert(todos('todo-1', [['Só planejar', 'in_progress']]))
  await expect(page.getByTestId('turn-tasks')).toBeVisible()
  await expect(page.getByTestId('work-block')).toHaveCount(0)
  await expect(page.getByTestId('turn-live')).toBeVisible()
})

const animations = (page: Page) =>
  page.locator('[data-test="turn-task-mark"], [data-test="turn-live-dot"]').evaluateAll((els) =>
    els.map((el) => getComputedStyle(el).animationName),
  )

test('o círculo laranja gira e os pontos pulsam; com movimento reduzido nada gira nem pulsa', async ({ page }) => {
  const turn = await stageRunningTurn(page)
  await turn.upsert(todos('todo-1', [['Fazer', 'in_progress'], ['Depois', 'pending']]))
  await expect(page.getByTestId('turn-task-mark').first()).toBeVisible()
  const moving = await animations(page)
  expect(moving.filter((name) => name !== 'none').length).toBeGreaterThanOrEqual(4) // the spinner and the 3 dots

  await page.emulateMedia({ reducedMotion: 'reduce' })
  await expect.poll(async () => (await animations(page)).every((name) => name === 'none')).toBe(true)
})

test('um turno seguinte sem ferramenta de tarefa não repete a lista', async ({ page }) => {
  const turn = await stageRunningTurn(page)
  await turn.upsert(todos('todo-1', [['Mapear o código', 'completed']]))
  await turn.finish()
  await turn.upsert({ type: 'user', id: 'user-2', text: 'Só uma pergunta', images: [], at: nowSeconds() })
  await turn.upsert({ type: 'text', id: 'txt-2', text: 'Resposta curta.', streaming: false, parent_tool_use_id: null, at: nowSeconds() })
  await expect(page.getByTestId('turn-end-label')).toHaveCount(2)
  await expect(page.getByTestId('turn-tasks')).toHaveCount(1) // only the turn that touched the list
})

test('em tela estreita o texto da linha viva trunca sem estourar a largura', async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 700 })
  const turn = await stageRunningTurn(page, { tokens: 1600 })
  await turn.upsert(running('b1', 'Bash', {
    command: 'pnpm --dir frontend exec vitest run src/components/conversation/__tests__/TurnProgress.spec.ts --reporter verbose',
    description: 'Rodar uma suíte de testes com um nome bem comprido para não caber na linha',
  }))
  const live = page.getByTestId('turn-live')
  await expect(live.getByTestId('turn-live-activity')).toContainText('Rodar uma suíte')
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
  expect(overflow).toBeLessThanOrEqual(0)
  const box = (await live.boundingBox())!
  expect(box.x + box.width).toBeLessThanOrEqual(360)
})
