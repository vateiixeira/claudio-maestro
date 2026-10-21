import type { Page, WebSocketRoute } from '@playwright/test'
import { expect, test } from './fixtures'

// The seeded server refuses the real agent and the terminal is a real shell, so the backend is staged:
// the snapshot of a seeded conversation carries a reply with a shell block, the terminal socket is one
// the spec writes to (like the backend would) and the run / message POSTs are answered by the spec.

type Item = Record<string, unknown>

const COMMAND = 'ls -la'
const ASSISTANT_ID = 'a-terminal-e2e'

async function stageTerminal(page: Page, options: { runStatus?: number } = {}) {
  const server = {
    seq: 0,
    items: [] as Item[],
    runs: [] as string[],
    messages: [] as Array<{ text: string }>,
  }
  let events: WebSocketRoute | null = null
  let terminal: WebSocketRoute | null = null
  await page.routeWebSocket(/\/ws$/, (ws) => {
    events = ws
  })
  await page.routeWebSocket(/\/ws\/terminal\//, (ws) => {
    terminal = ws
    ws.send(JSON.stringify({ type: 'replay', data: '', cols: 80, rows: 24 }))
  })
  await page.route(/\/api\/sessions\/[0-9a-f-]+$/, async (route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    const response = await route.fetch()
    const snapshot = await response.json()
    await route.fulfill({
      response,
      json: {
        ...snapshot,
        seq: server.seq,
        items: [
          ...snapshot.items,
          {
            type: 'text',
            id: ASSISTANT_ID,
            text: `Rode este comando:\n\n\`\`\`bash\n${COMMAND}\n\`\`\`\n\nE depois me conte.`,
            streaming: false,
            parent_tool_use_id: null,
          },
          ...server.items,
        ],
      },
    })
  })
  await page.route(/\/api\/sessions\/[0-9a-f-]+\/terminal\/run$/, async (route) => {
    server.runs.push((route.request().postDataJSON() as { command: string }).command)
    if (options.runStatus === 409) {
      await route.fulfill({ status: 409, json: { detail: 'O terminal está ocupado.' } })
      return
    }
    await route.fulfill({ status: 202, json: { run_id: 'run-1' } })
  })
  await page.route(/\/api\/sessions\/[0-9a-f-]+\/messages$/, async (route) => {
    server.messages.push(route.request().postDataJSON() as { text: string })
    await route.fulfill({ json: { state: 'working', external_activity: false } })
  })
  await page.goto('/sessions')
  await page.getByText('Explique a estrutura do projeto').first().click()
  const sessionId = page.url().match(/[0-9a-f]{8}-[0-9a-f-]{27}/)?.[0] ?? ''
  return {
    server,
    sessionId,
    /** A frame of the terminal socket, as the backend would send it. */
    async frame(data: Item) {
      await expect.poll(() => terminal !== null).toBe(true)
      terminal!.send(JSON.stringify(data))
    },
    /** An event of the conversation socket. */
    async upsert(item: Item) {
      await expect.poll(() => events !== null).toBe(true)
      server.seq += 1
      server.items.push(item)
      events!.send(JSON.stringify({ session_id: sessionId, seq: server.seq, type: 'item.upsert', data: item }))
    },
  }
}

const playButton = (page: Page) => page.locator(`[data-item-id="${ASSISTANT_ID}"]`).getByRole('button', { name: /Rodar no terminal|Rodando|Enviado|Interrompido|O terminal está ocupado/ })

async function revealPlay(page: Page) {
  const block = page.locator(`[data-item-id="${ASSISTANT_ID}"] .code-block`)
  await expect(block).toBeVisible()
  await block.hover()
  return block
}

test('o play abre a aba Terminal, mostra "Enviado · código 0" e a caixa "Rodou no terminal"', async ({ page }) => {
  const t = await stageTerminal(page)
  await revealPlay(page)
  await expect(playButton(page)).toHaveText('Rodar')

  await playButton(page).click()
  await expect.poll(() => t.server.runs).toEqual([COMMAND])
  await expect(page.getByTestId('details-tab-terminal')).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByTestId('terminal-pane')).toBeVisible()

  await t.frame({ type: 'busy', busy: true })
  await t.frame({ type: 'run', run_id: 'run-1', state: 'running', exit_code: null })
  await expect(playButton(page)).toHaveText('Rodando…')
  await t.frame({ type: 'busy', busy: false })
  await t.frame({ type: 'run', run_id: 'run-1', state: 'sent', exit_code: 0 })
  await expect(playButton(page)).toHaveText('Enviado · código 0')

  await t.upsert({
    type: 'user',
    id: 'u-terminal-run',
    text: '',
    at: Math.floor(Date.now() / 1000),
    terminal_run: { command: COMMAND, output: 'total 0', exit_code: 0, duration_ms: 320, notes: [] },
  })
  const box = page.locator('[data-item-id="u-terminal-run"]')
  await expect(box.getByText('Rodou no terminal')).toBeVisible()
  await expect(box.getByText('Você', { exact: true })).toBeVisible()
  await expect(box.getByTestId('terminal-run-command')).toContainText(COMMAND)
  await expect(box).toContainText('código 0')
})

test('Copiar e Rodar ficam lado a lado, sem se sobrepor', async ({ page }) => {
  await stageTerminal(page)
  const block = await revealPlay(page)
  const play = block.getByRole('button', { name: 'Rodar no terminal' })
  const copy = block.getByRole('button', { name: 'Copiar código' })
  await expect(play).toBeVisible()
  await expect(copy).toBeVisible()
  const a = (await play.boundingBox())!
  const b = (await copy.boundingBox())!
  const overlap = a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height
  expect(overlap, 'os botões Rodar e Copiar não podem se sobrepor').toBe(false)
})

test('"Anexar tela" vira o chip "Trecho do terminal" e o envio leva o prefixo de anexo', async ({ page }) => {
  const t = await stageTerminal(page)
  await expect(page.locator(`[data-item-id="${ASSISTANT_ID}"]`)).toBeVisible()
  await page.getByTestId('terminal-button').click()
  await expect(page.getByTestId('terminal-pane')).toBeVisible()
  await t.frame({ type: 'output', data: 'saida-do-terminal\r\n' })
  await expect(page.getByTestId('terminal-screen')).toContainText('saida-do-terminal')

  await page.getByTestId('terminal-attach-screen').click()
  const chip = page.getByTestId('terminal-attachment')
  await expect(chip).toContainText('Trecho do terminal')
  await expect(chip).toContainText('saida-do-terminal')

  await page.getByRole('button', { name: 'Enviar' }).click()
  await expect.poll(() => t.server.messages.length).toBe(1)
  expect(t.server.messages[0]!.text).toBe('<!-- attach: Terminal -->\n> saida-do-terminal')
  await expect(chip).toHaveCount(0)
})

test('409 no run mostra "O terminal está ocupado"', async ({ page, consoleErrors }) => {
  const t = await stageTerminal(page, { runStatus: 409 })
  await revealPlay(page)
  await playButton(page).click()
  await expect.poll(() => t.server.runs).toEqual([COMMAND])
  await expect(playButton(page)).toHaveText('O terminal está ocupado')
  // The browser logs the 409 itself; anything else is still a failure.
  expect(consoleErrors.filter((m) => !m.includes('409'))).toEqual([])
  consoleErrors.length = 0
})

test('a aba Detalhes continua funcionando e a troca de aba não perde o terminal', async ({ page }) => {
  const t = await stageTerminal(page)
  await expect(page.locator(`[data-item-id="${ASSISTANT_ID}"]`)).toBeVisible()
  await page.getByTestId('terminal-button').click()
  await t.frame({ type: 'output', data: 'continua-aqui\r\n' })
  await expect(page.getByTestId('terminal-screen')).toContainText('continua-aqui')

  await page.getByTestId('details-tab-details').click()
  await expect(page.getByTestId('details-tab-details')).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByTestId('terminal-pane')).toHaveCount(0)
  await expect(page.getByTestId('details-body')).toBeVisible()

  await page.getByTestId('details-tab-terminal').click()
  await expect(page.getByTestId('terminal-screen')).toContainText('continua-aqui')
})

test('Finalizar com o terminal ocupado pede confirmação', async ({ page }) => {
  const t = await stageTerminal(page)
  await expect(page.locator(`[data-item-id="${ASSISTANT_ID}"]`)).toBeVisible()
  await page.getByTestId('terminal-button').click()
  await t.frame({ type: 'busy', busy: true })

  await page.getByTestId('toggle-finished').click()
  const dialog = page.getByRole('dialog', { name: 'Finalizar com o terminal rodando?' })
  await expect(dialog).toBeVisible()
  await dialog.getByTestId('confirm-cancel').click()
  await expect(dialog).toHaveCount(0)
  await expect(page.getByTestId('toggle-finished')).toHaveText('Finalizar')
})
