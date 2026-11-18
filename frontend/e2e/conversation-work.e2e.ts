import type { Page } from '@playwright/test'
import { expect, openSeededSession, test } from './fixtures'

// The seeded conversations have no tool actions, so a second turn is appended to the snapshot of a
// seeded conversation. Times are fixed, so the duration of the block does not depend on the clock.
type Item = Record<string, unknown>
const T0 = 1794960000
const ok = { content: 'ok', is_error: false, details: null }
const failed = (message: string) => ({ content: message, is_error: true, details: null })

const user = (id: string, text: string, at: number): Item => ({ type: 'user', id, text, images: [], at, remote: false, terminal_run: null, terminal_snippets: [] })
const text = (id: string, body: string, at: number): Item => ({ type: 'text', id, text: body, streaming: false, parent_tool_use_id: null, at })
const tool = (id: string, name: string, input: Record<string, unknown>, at: number, result: Item = ok, extra: Item = {}): Item => ({
  type: 'tool', id, tool_use_id: `tu-${id}`, name, input, result, streaming: false, parent_tool_use_id: null, at, ...extra,
})

async function stage(page: Page, items: Item[]) {
  await page.route(/\/api\/sessions\/[0-9a-f-]+$/, async (route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    const response = await route.fetch()
    const snapshot = await response.json()
    await route.fulfill({ response, json: { ...snapshot, items: [...snapshot.items, ...items] } })
  })
  await openSeededSession(page)
}

// First block: a command fails and the next one, of the same program, passes; then a read, in another
// folder; then two edits. Second block (after a text): a read that fails and is not tried again.
const REDONE: Item[] = [
  user('u2', 'Rode os testes da loja', T0),
  tool('b1', 'Bash', { command: 'cd /tmp/loja-demo && pnpm test', description: 'Rodar os testes' }, T0 + 1, failed('Error: 2 tests failed\n  at suite.test.ts:14')),
  tool('b2', 'Bash', { command: 'cd /tmp/loja-demo && pnpm test --retry 1', description: 'Rodar os testes de novo' }, T0 + 5),
  tool('r1', 'Read', { file_path: '/tmp/loja-demo/leia-me.md' }, T0 + 8),
  tool('e1', 'Edit', { file_path: '/tmp/loja-demo/carrinho.ts', old_string: 'a = 1', new_string: 'a = 2\nb = 3' }, T0 + 10),
  text('t2', 'Os testes passaram.', T0 + 20),
  tool('r2', 'Read', { file_path: '/tmp/loja-demo/faltando.md' }, T0 + 22, failed('ENOENT: arquivo não existe')),
  tool('b3', 'Bash', { command: 'ls /tmp/loja-demo', description: 'Listar a pasta' }, T0 + 24),
  text('t3', 'Terminei.', T0 + 30),
]

test('as ações do bloco ficam em grupos por tipo, com a pasta e a duração no cabeçalho', async ({ page }) => {
  await stage(page, REDONE)
  const block = page.getByTestId('work-block').first()
  await expect(block.getByTestId('work-count')).toHaveText('4 ações')
  await expect(block.getByTestId('work-span')).toHaveText('19 s')
  await expect(block.getByTestId('work-group')).toHaveCount(0)

  await block.getByTestId('work-block-toggle').click()
  const groups = block.getByTestId('work-group')
  await expect(groups).toHaveCount(3)
  await expect(groups.nth(0).getByTestId('work-group-label')).toHaveText('Comandos')
  await expect(groups.nth(0).getByTestId('work-group-where')).toContainText('/tmp/loja-demo')
  await expect(groups.nth(0).getByTestId('work-group-count')).toHaveText('2')
  await expect(groups.nth(1).getByTestId('work-group-label')).toHaveText('Leituras')
  await expect(groups.nth(2).getByTestId('work-group-label')).toHaveText('Edições')
  // Each action is a row of its group; the row carries no label of its kind.
  await expect(groups.nth(0).getByTestId('work-row')).toHaveCount(2)
  await expect(groups.nth(0).getByTestId('work-row').first().getByTestId('work-desc')).toHaveText('Rodar os testes')
  await expect(block.getByTestId('work-row')).toHaveCount(4)
})

test('uma falha refeita com sucesso diz "refeita em seguida", marca a nova tentativa e não abre o bloco', async ({ page }) => {
  await stage(page, REDONE)
  const block = page.getByTestId('work-block').first()
  const toggle = block.getByTestId('work-block-toggle')
  await expect(block.getByTestId('work-failed')).toHaveText('1 falhou, refeita em seguida')
  await expect(toggle).toHaveAttribute('aria-expanded', 'false')
  await expect(block.getByTestId('work-row')).toHaveCount(0)

  await toggle.click()
  const rows = block.getByTestId('work-row')
  await expect(rows.nth(0).getByTestId('work-retry')).toHaveCount(0)
  await expect(rows.nth(1).getByTestId('work-retry')).toHaveText('Nova tentativa')
  // The failed row itself opens with the block: the error band and the note that the next attempt passed.
  await expect(rows.nth(0).getByTestId('work-error-text')).toHaveText('Error: 2 tests failed')
  await expect(rows.nth(0).getByTestId('work-retry-note')).toHaveText('A tentativa seguinte passou.')
  // Only the failure nobody tried again (second block) leaves a red node in the rail.
  await expect(page.locator('[data-test="rail-node"][data-kind="error"]')).toHaveCount(1)
})

test('uma falha sem nova tentativa abre o bloco sozinha, com a faixa de erro e o botão de copiar', async ({ page, context }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write'])
  await stage(page, REDONE)
  const block = page.getByTestId('work-block').nth(1)
  await expect(block.getByTestId('work-count')).toHaveText('2 ações')
  await expect(block.getByTestId('work-block-toggle')).toHaveAttribute('aria-expanded', 'true')
  await expect(block.getByTestId('work-failed')).toHaveText('1 falhou')
  await expect(block.getByTestId('work-retry')).toHaveCount(0)

  const failedRow = block.getByTestId('work-row').first()
  await expect(failedRow.getByTestId('work-error-text')).toHaveText('ENOENT: arquivo não existe')
  await expect(failedRow.getByTestId('work-retry-note')).toHaveCount(0)
  const copy = failedRow.getByRole('button', { name: 'Copiar erro' })
  await copy.click()
  await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe('ENOENT: arquivo não existe')
})

test('com o bloco fechado, os chips mostram o que ele produziu e o clique abre a linha da ação', async ({ page }) => {
  await stage(page, [
    user('u2', 'Edite o carrinho', T0),
    tool('e1', 'Edit', { file_path: '/tmp/loja-demo/carrinho.ts', old_string: 'a = 1', new_string: 'a = 2\nb = 3' }, T0 + 1),
    tool('e2', 'Write', { file_path: '/tmp/loja-demo/preco.ts', content: 'export const preco = 1\n' }, T0 + 3),
    tool('ag', 'Agent', { subagent_type: 'implementer', description: 'Criar o módulo novo' }, T0 + 4, ok, {
      subagent: {
        task_id: 't1', subagent_type: 'implementer', description: 'Criar o módulo novo', status: 'completed',
        last_activity: null, usage: { total_tokens: 31000, tool_uses: 4, duration_ms: 228000 }, summary: 'Pronto.',
      },
    }),
    text('t2', 'Feito.', T0 + 240),
  ])
  const block = page.getByTestId('work-block').first()
  const toggle = block.getByTestId('work-block-toggle')
  await expect(toggle).toHaveAttribute('aria-expanded', 'false')
  const files = block.getByTestId('work-file-chip')
  await expect(files).toHaveCount(2)
  await expect(files.first()).toContainText('carrinho.ts')
  await expect(files.first()).toContainText('+2')
  await expect(files.first()).toContainText('−1')
  await expect(files.nth(1)).toContainText('preco.ts')
  const agent = block.getByTestId('work-agent-chip')
  await expect(agent).toContainText('Criar o módulo novo')
  await expect(agent.getByTestId('work-agent-meta')).toContainText('31 mil tokens')

  // A click opens the block on the row behind the chip; open, the chips are gone (the rows show it).
  await files.nth(1).click()
  await expect(toggle).toHaveAttribute('aria-expanded', 'true')
  await expect(block.getByTestId('work-file-chip')).toHaveCount(0)
  await expect(block.getByTestId('work-agent-chip')).toHaveCount(0)
  const rows = block.getByTestId('work-row')
  await expect(rows).toHaveCount(3)
  await expect(rows.nth(1).getByTestId('work-row-body')).toBeVisible()
  await expect(rows.nth(0).getByTestId('work-row-body')).toBeHidden()
})

test('o separador de cada turno traz o número e as contagens do turno', async ({ page }) => {
  await stage(page, REDONE)
  const numbers = page.getByTestId('turn-number')
  await expect(numbers).toHaveText(['Turno 1', 'Turno 2'])
  // The first turn has no action; the second has 6 actions and one file edited.
  await expect(page.getByTestId('turn-stats')).toHaveCount(1)
  await expect(page.getByTestId('turn-stats')).toHaveText('6 ações · 1 arquivo alterado')
})

test('o bloco aberto, a falha e o compositor não geram rolagem horizontal em 360, 768 e 1440', async ({ page }) => {
  const long = 'cd /tmp/loja-demo && pnpm --dir frontend exec vitest run src/components/conversation/__tests__/WorkBlockComMuitoTexto.spec.ts --reporter verbose'
  await stage(page, [
    user('u2', 'Rode os testes da loja', T0),
    tool('b1', 'Bash', { command: long, description: 'Rodar uma suíte de testes com um nome bem comprido que não cabe na linha' }, T0 + 1, failed(`Error: ${'falha muito comprida '.repeat(12)}`)),
    tool('e1', 'Edit', { file_path: '/tmp/loja-demo/src/components/carrinho/CarrinhoComUmNomeMuitoCompridoDeArquivo.vue', old_string: 'a', new_string: 'b' }, T0 + 3),
    text('t2', 'Pronto.', T0 + 9),
  ])
  const block = page.getByTestId('work-block').first()
  await block.getByTestId('work-block-toggle').click()
  await expect(block.getByTestId('work-error')).toBeVisible()
  for (const width of [360, 768, 1440]) {
    await page.setViewportSize({ width, height: 900 })
    const fits = await page.evaluate(() => {
      const main = document.querySelector('main')!
      return main.scrollWidth <= main.clientWidth && document.documentElement.scrollWidth <= innerWidth
    })
    expect(fits, `sem rolagem horizontal em ${width}px`).toBe(true)
  }
})

// Text of the redesigned conversation stays readable (4.5:1) in each of the eight themes.
const THEME_IDS = ['maestro', 'dracula', 'monokai-pro', 'monokai-machine', 'monokai-octagon', 'monokai-ristretto', 'monokai-spectrum', 'monokai-classic']
const READABLE = [
  'work-summary', 'work-failed', 'work-span', 'work-group-label', 'work-group-where', 'work-group-count', 'work-retry',
  'work-command', 'work-error-text', 'work-retry-note', 'work-file-chip', 'turn-number', 'turn-stats', 'turn-end-label', 'composer-hint',
]

for (const theme of THEME_IDS) {
  test(`o texto do bloco, do turno e do compositor tem contraste de 4,5:1 no tema ${theme}`, async ({ page }) => {
    await stage(page, [
      ...REDONE,
      tool('e9', 'Edit', { file_path: '/tmp/loja-demo/preco.ts', old_string: 'a', new_string: 'b\nc' }, T0 + 40),
      text('t4', 'Fim.', T0 + 50),
    ])
    // The first block, opened; the third (a closed one with a chip of a file); the second opens by itself (failure).
    await page.getByTestId('work-block').first().getByTestId('work-block-toggle').click()
    await expect(page.getByTestId('work-file-chip')).toHaveCount(1)
    await page.evaluate((id) => {
      if (id === 'maestro') document.documentElement.removeAttribute('data-theme')
      else document.documentElement.setAttribute('data-theme', id)
    }, theme)
    const readability = () => page.evaluate((names) => {
      const probe = document.createElement('canvas').getContext('2d', { willReadFrequently: true })!
      const rgba = (css: string): [number, number, number, number] => {
        probe.clearRect(0, 0, 1, 1)
        probe.fillStyle = '#000'
        probe.fillStyle = css
        probe.fillRect(0, 0, 1, 1)
        const d = probe.getImageData(0, 0, 1, 1).data
        return [d[0]!, d[1]!, d[2]!, d[3]! / 255]
      }
      const over = (top: number[], below: number[]) => {
        const a = top[3]!
        return [0, 1, 2].map((i) => top[i]! * a + below[i]! * (1 - a))
      }
      const lum = (c: number[]) => {
        const [r, g, b] = c.map((v) => { const s = v! / 255; return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4 })
        return 0.2126 * r! + 0.7152 * g! + 0.0722 * b!
      }
      const problems: string[] = []
      for (const name of names) {
        for (const el of document.querySelectorAll<HTMLElement>(`[data-test="${name}"]`)) {
          if (!el.getClientRects().length || !el.textContent?.trim()) continue
          // Background: the layers from the root down to the element, one over the other.
          const layers: number[][] = []
          for (let node: HTMLElement | null = el; node; node = node.parentElement) layers.push(rgba(getComputedStyle(node).backgroundColor))
          let bg = [0, 0, 0]
          for (const layer of layers.reverse()) bg = over(layer, bg)
          const fgRaw = rgba(getComputedStyle(el).color)
          const fg = over(fgRaw, bg)
          const [l1, l2] = [lum(fg), lum(bg)].sort((a, b) => b - a)
          const ratio = (l1! + 0.05) / (l2! + 0.05)
          if (ratio < 4.5) problems.push(`${name}: ${ratio.toFixed(2)}`)
        }
      }
      return problems
    }, READABLE)
    // Colors may still be in their transition right after the switch, so the check polls.
    await expect.poll(readability, { message: `contraste abaixo de 4,5:1 no tema ${theme}` }).toEqual([])
  })
}

test('o teclado abre o bloco, chega ao chip e à linha e o foco aparece', async ({ page }) => {
  await stage(page, [
    user('u2', 'Edite o carrinho', T0),
    tool('e1', 'Edit', { file_path: '/tmp/loja-demo/carrinho.ts', old_string: 'a = 1', new_string: 'a = 2' }, T0 + 1),
    tool('r1', 'Read', { file_path: '/tmp/loja-demo/leia-me.md' }, T0 + 3),
    text('t2', 'Feito.', T0 + 9),
  ])
  const block = page.getByTestId('work-block').first()
  const toggle = block.getByTestId('work-block-toggle')
  await toggle.focus()
  await expect(toggle).toBeFocused()
  expect(await toggle.evaluate((el) => getComputedStyle(el).outlineStyle)).not.toBe('none')
  // Tab goes to the chip of the edited file; Enter opens the block on that row.
  await page.keyboard.press('Tab')
  const chip = block.getByTestId('work-file-chip')
  await expect(chip).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(toggle).toHaveAttribute('aria-expanded', 'true')
  await expect(block.getByTestId('work-row')).toHaveCount(2)
  await expect(block.getByTestId('work-row').first().getByTestId('work-row-body')).toBeVisible()
  // Each row is a button of the keyboard: Space opens the other one.
  const header = block.getByTestId('work-row').nth(1).getByTestId('work-header')
  await header.focus()
  await page.keyboard.press('Space')
  await expect(header).toHaveAttribute('aria-expanded', 'true')
  expect(await header.evaluate((el) => getComputedStyle(el).outlineStyle)).not.toBe('none')
  // Enter on the toggle closes the block again.
  await toggle.focus()
  await page.keyboard.press('Enter')
  await expect(toggle).toHaveAttribute('aria-expanded', 'false')
})
