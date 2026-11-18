import type { Page } from '@playwright/test'
import { expect, openSeededSession, test } from './fixtures'

type Item = Record<string, unknown>
const ok = { content: 'ok', is_error: false, details: null }

const agent = (id: string, description: string, status: 'running' | 'completed'): Item => ({
  type: 'tool', id, tool_use_id: `tu-${id}`, name: 'Agent',
  input: { subagent_type: 'implementer', description },
  result: status === 'running' ? null : ok, streaming: status === 'running', parent_tool_use_id: null,
  subagent: {
    task_id: `task-${id}`, subagent_type: 'implementer', description, status, last_activity: null,
    usage: null, summary: status === 'running' ? null : 'Pronto.',
  },
})

async function stageSubagents(page: Page, items: Item[]) {
  await page.route(/\/api\/sessions\/[0-9a-f-]+$/, async (route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    const response = await route.fetch()
    const snapshot = await response.json()
    await route.fulfill({ response, json: { ...snapshot, items: [...snapshot.items, ...items] } })
  })
}

test('o compositor é uma moldura só: campo e barra de controles dentro, sem dica de teclado', async ({ page }) => {
  await openSeededSession(page)
  const frame = page.getByTestId('composer-frame')
  const box = page.getByRole('combobox', { name: 'Mensagem para a sessão' })
  const toolbar = frame.getByTestId('composer-toolbar')
  await expect(frame).toBeVisible()
  await expect(frame.getByRole('combobox')).toHaveCount(1)
  await expect(toolbar.getByTestId('send')).toBeVisible()
  await expect(toolbar.getByTestId('composer-options')).toBeVisible()

  await expect(page.getByTestId('composer-hint')).toHaveCount(0)
  await expect(page.getByText('Enter envia · Ctrl+Enter quebra linha')).toHaveCount(0)
  const frameBox = (await frame.boundingBox())!
  const fieldBox = (await box.boundingBox())!
  const toolbarBox = (await toolbar.boundingBox())!
  // Field above the toolbar, both inside the frame.
  expect(fieldBox.y + fieldBox.height).toBeLessThanOrEqual(toolbarBox.y + 1)
  expect(toolbarBox.y + toolbarBox.height).toBeLessThanOrEqual(frameBox.y + frameBox.height + 1)
})

test('a lista de / e de @ abre acima do campo, inteira e sem corte, e o realce acompanha o texto', async ({ page }) => {
  await page.route(/\/api\/sessions\/[0-9a-f-]+\/commands$/, (route) => route.fulfill({
    json: [
      { name: 'review', description: 'Revisar a mudança', argument_hint: '' },
      { name: 'compact', description: 'Resumir a conversa', argument_hint: '[instruções]' },
    ],
  }))
  await page.route(/\/api\/sessions\/[0-9a-f-]+\/files\?/, (route) => route.fulfill({
    json: [{ path: '/tmp/loja-demo/src/app.ts', name: 'src/app.ts', type: 'file' }],
  }))
  await openSeededSession(page)
  const field = page.getByRole('combobox', { name: 'Mensagem para a sessão' })
  const list = page.getByRole('listbox', { name: 'Sugestões' })

  async function expectAboveAndWhole() {
    await expect(list).toBeVisible()
    const listBox = (await list.boundingBox())!
    const fieldBox = (await field.boundingBox())!
    const viewport = page.viewportSize()!
    expect(listBox.y + listBox.height).toBeLessThanOrEqual(fieldBox.y + 1)
    expect(listBox.y).toBeGreaterThanOrEqual(0)
    expect(listBox.x).toBeGreaterThanOrEqual(0)
    expect(listBox.x + listBox.width).toBeLessThanOrEqual(viewport.width)
    // Nothing clips it: each corner of the list is a point of the list itself, on top of the page.
    for (const [x, y] of [[8, 8], [listBox.width - 9, 8], [listBox.width - 9, listBox.height - 9], [8, listBox.height - 9]] as const) {
      const inside = await page.evaluate(([px, py]) => {
        const hit = document.elementFromPoint(px, py)
        return !!hit?.closest('[role="listbox"]')
      }, [listBox.x + x, listBox.y + y])
      expect(inside, `ponto ${x},${y} da lista`).toBe(true)
    }
  }

  await field.click()
  await field.fill('/')
  await expect(list.getByRole('option')).toHaveCount(2)
  await expectAboveAndWhole()
  await field.press('Escape')
  await expect(list).toHaveCount(0)

  // Typed like a person does, key by key, so the menu sees the same events a user makes.
  await field.fill('')
  await field.pressSequentially('veja @app')
  await expect(list.getByRole('option', { name: /app\.ts/ })).toBeVisible()
  await expectAboveAndWhole()
  await list.getByRole('option', { name: /app\.ts/ }).click()
  await expect(list).toHaveCount(0)

  // The highlight layer lays the text out like the field: same box, padding and font.
  const mark = page.locator('[data-test="composer-frame"] mark')
  await expect(mark).toHaveCount(1)
  const layout = await page.evaluate(() => {
    const textarea = document.querySelector<HTMLTextAreaElement>('[data-test="composer-frame"] textarea')!
    const mirror = textarea.parentElement!.querySelector<HTMLElement>('[aria-hidden="true"]')!
    const pick = (el: Element) => {
      const s = getComputedStyle(el)
      const r = el.getBoundingClientRect()
      return { x: r.x, y: r.y, w: r.width, h: r.height, pl: s.paddingLeft, pt: s.paddingTop, font: s.fontSize + s.fontFamily, lh: s.lineHeight }
    }
    return { textarea: pick(textarea), mirror: pick(mirror) }
  })
  expect(layout.mirror).toEqual(layout.textarea)
  // The mention is highlighted on the same line the text is typed on (the first one of the field).
  const markBox = (await mark.boundingBox())!
  const mirrorBox = (await page.locator('[data-test="composer-frame"] textarea').boundingBox())!
  expect(markBox.x).toBeGreaterThanOrEqual(mirrorBox.x)
  expect(markBox.y).toBeGreaterThanOrEqual(mirrorBox.y)
  expect(markBox.y + markBox.height).toBeLessThanOrEqual(mirrorBox.y + mirrorBox.height)
})

test('a faixa de subagentes fica dentro da moldura, acima do campo, e "Parar subagente" chama o servidor', async ({ page }) => {
  await stageSubagents(page, [agent('a1', 'Criar o módulo novo', 'running'), agent('a2', 'Revisar o módulo', 'completed')])
  let stops = 0
  await page.route(/\/api\/sessions\/[0-9a-f-]+\/subagents\/stop$/, (route) => {
    stops += 1
    return route.fulfill({ status: 204, body: '' })
  })
  await openSeededSession(page)
  const frame = page.getByTestId('composer-frame')
  const strip = frame.getByTestId('subagent-strip')
  await expect(strip).toBeVisible()
  await expect(strip).toHaveAccessibleName('Subagentes')
  await expect(strip.getByTestId('subagent-counts')).toContainText('1 rodando')
  await expect(strip.getByTestId('subagent-counts')).toContainText('1 concluído')
  await expect(strip.getByTestId('subagent-current')).toContainText('Criar o módulo novo')
  // Up to three, the list shows by itself; no toggle.
  await expect(strip.getByTestId('subagent-row')).toHaveCount(2)
  await expect(strip.getByTestId('subagent-summary')).toHaveCount(0)

  const stripBox = (await strip.boundingBox())!
  const frameBox = (await frame.boundingBox())!
  const fieldBox = (await frame.getByRole('combobox').boundingBox())!
  expect(stripBox.y).toBeGreaterThanOrEqual(frameBox.y)
  expect(stripBox.x).toBeGreaterThanOrEqual(frameBox.x)
  expect(stripBox.x + stripBox.width).toBeLessThanOrEqual(frameBox.x + frameBox.width + 1)
  expect(stripBox.y + stripBox.height).toBeLessThanOrEqual(fieldBox.y + 1)

  await strip.getByRole('button', { name: 'Parar subagente' }).click()
  await expect.poll(() => stops).toBe(1)
})

test('com mais de três subagentes a lista vem recolhida e a seta a abre', async ({ page }) => {
  await stageSubagents(page, [
    agent('a1', 'Primeiro', 'completed'), agent('a2', 'Segundo', 'completed'), agent('a3', 'Terceiro', 'completed'),
    agent('a4', 'Quarto', 'completed'), agent('a5', 'Quinto', 'running'),
  ])
  await openSeededSession(page)
  const strip = page.getByTestId('composer-frame').getByTestId('subagent-strip')
  await expect(strip.getByTestId('subagent-counts')).toContainText('1 rodando · 4 concluídos')
  await expect(strip.getByTestId('subagent-row')).toHaveCount(0)
  const toggle = strip.getByTestId('subagent-summary')
  await expect(toggle).toHaveAttribute('aria-expanded', 'false')
  await toggle.click()
  await expect(toggle).toHaveAttribute('aria-expanded', 'true')
  await expect(strip.getByTestId('subagent-row')).toHaveCount(5)
})

test('o teclado percorre a barra de controles e o foco aparece nos botões', async ({ page }) => {
  await openSeededSession(page)
  const frame = page.getByTestId('composer-frame')
  const field = frame.getByRole('combobox')
  await field.click()
  await field.fill('oi')
  // Tab leaves the field and walks the toolbar until "Enviar", which is enabled now.
  const send = frame.getByTestId('send')
  await expect(send).toBeEnabled()
  let reached = false
  for (let i = 0; i < 12 && !reached; i++) {
    await page.keyboard.press('Tab')
    reached = await send.evaluate((el) => el === document.activeElement)
  }
  expect(reached, '"Enviar" alcançado com Tab').toBe(true)
  await expect(send).toBeFocused()
  const outline = await send.evaluate((el) => getComputedStyle(el).outlineStyle)
  expect(outline).not.toBe('none')
  // The frame keeps the draft while the focus travels.
  await expect(field).toHaveValue('oi')
})

test('com o painel Detalhes aberto em 1440 px e um turno rodando, Ditado, Interromper e Enviar ficam juntos na primeira linha da barra', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  // The server plays no agent: the snapshot says the turn runs, and the socket is one the spec owns.
  await page.routeWebSocket(/\/ws$/, () => {})
  await page.route(/\/api\/sessions\/[0-9a-f-]+$/, async (route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    const response = await route.fetch()
    const snapshot = await response.json()
    await route.fulfill({ response, json: { ...snapshot, state: 'running', turn_started_at: Math.floor(Date.now() / 1000) - 30 } })
  })
  await openSeededSession(page)
  await expect(page.getByTestId('turn-number').first()).toBeVisible()
  if (!(await page.getByTestId('details-panel').isVisible())) await page.getByTestId('toggle-details').first().click()
  await expect(page.getByTestId('details-panel')).toBeVisible()

  const toolbar = page.getByTestId('composer-toolbar')
  const interrupt = toolbar.getByTestId('interrupt')
  await expect(interrupt).toBeVisible()
  const options = (await toolbar.getByTestId('composer-options').boundingBox())!
  const boxes = [await toolbar.getByTestId('dictate').boundingBox(), (await interrupt.boundingBox()), await toolbar.getByTestId('send').boundingBox()]
  for (const box of boxes) {
    expect(box).not.toBeNull()
    expect(box!.y).toBeCloseTo(boxes[0]!.y, 0)
    expect(box!.x).toBeGreaterThanOrEqual(options.x + options.width - 1)
  }
})
