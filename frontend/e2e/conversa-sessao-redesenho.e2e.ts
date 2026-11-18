import type { Page } from '@playwright/test'
import { expect, openSeededSession, test } from './fixtures'

// Marco 40: cabeçalho, barra do turno, "Copiar", avisos e barra do compositor da conversa.
// The seeded conversations have a single turn, so extra turns and notices are appended to the snapshot.
type Item = Record<string, unknown>
const T0 = 1794960000
const user = (id: string, body: string, at: number): Item => ({ type: 'user', id, text: body, images: [], at, remote: false, terminal_run: null, terminal_snippets: [] })
const text = (id: string, body: string, at: number): Item => ({ type: 'text', id, text: body, streaming: false, parent_tool_use_id: null, at })
const notice = (id: string, level: string, body: string): Item => ({ type: 'notice', id, level, text: body, at: T0 + 100 })

const EXTRA_TURNS: Item[] = [
  user('u2', 'Segunda pergunta', T0), text('t2', 'Segunda resposta', T0 + 5),
  user('u3', 'Terceira pergunta', T0 + 10), text('t3', 'Terceira resposta', T0 + 15),
]

async function stage(page: Page, items: Item[], patch: Item = {}) {
  await page.route(/\/api\/sessions\/[0-9a-f-]+$/, async (route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    const response = await route.fetch()
    const snapshot = await response.json()
    await route.fulfill({ response, json: { ...snapshot, ...patch, items: [...snapshot.items, ...items] } })
  })
}

async function openWithDetails(page: Page) {
  await page.setViewportSize({ width: 1440, height: 900 })
  await openSeededSession(page)
  await expect(page.getByTestId('composer-toolbar')).toBeVisible()
  const toggle = page.getByTestId('toggle-details').first()
  if ((await toggle.getAttribute('aria-pressed')) !== 'true') await toggle.click()
  await expect(page.getByTestId('details-panel')).toBeVisible()
}

async function noHorizontalScroll(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
  expect(overflow).toBeLessThanOrEqual(0)
}

test('com Detalhes abertos em 1440 px, as opções do compositor e o Enviar ficam na mesma linha', async ({ page }) => {
  await openWithDetails(page)
  const toolbar = page.getByTestId('composer-toolbar')
  const options = (await toolbar.getByTestId('composer-options').boundingBox())!
  const send = (await toolbar.getByTestId('send').boundingBox())!
  expect(Math.abs((options.y + options.height / 2) - (send.y + send.height / 2))).toBeLessThan(options.height / 2 + 2)
  expect(options.height).toBeLessThan(45)
})

test('o compositor mostra o Remote Control só com ícone, o modelo curto e as Permissões sem prefixo', async ({ page }) => {
  await openWithDetails(page)
  const options = page.getByTestId('composer-options')
  const remote = options.getByRole('button', { name: /^Remote Control/ })
  await expect(remote).toBeVisible()
  await expect(remote).toHaveAccessibleName(/Remote Control/)
  const box = (await remote.boundingBox())!
  expect(box.width).toBeLessThanOrEqual(40)

  const model = options.getByRole('button', { name: /^Modelo: / })
  const fullName = ((await model.getAttribute('aria-label')) ?? (await model.getAttribute('title')) ?? '')
  const visible = ((await model.innerText()) ?? '').trim()
  expect(visible.length).toBeGreaterThan(0)
  expect(visible).not.toMatch(/\)\s*$/)
  expect(await model.getAttribute('aria-label')).toMatch(/^Modelo: /)
  expect(fullName.length).toBeGreaterThanOrEqual(visible.length)

  const permissions = options.getByRole('button', { name: /^Permissões: / })
  await expect(permissions).toBeVisible()
  await expect(permissions).not.toContainText('Permissões')
  await expect(permissions).toHaveAccessibleName(/^Permissões: .+/)
})

test('com um turno rodando, Interromper e Enviar continuam na mesma linha das opções', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.routeWebSocket(/\/ws$/, () => {})
  await stage(page, [], { state: 'running', turn_started_at: Math.floor(Date.now() / 1000) - 30 })
  await openSeededSession(page)
  const toggle = page.getByTestId('toggle-details').first()
  if ((await toggle.getAttribute('aria-pressed')) !== 'true') await toggle.click()
  await expect(page.getByTestId('details-panel')).toBeVisible()
  const toolbar = page.getByTestId('composer-toolbar')
  const interrupt = toolbar.getByTestId('interrupt')
  await expect(interrupt).toBeVisible()
  const send = (await toolbar.getByTestId('send').boundingBox())!
  const stop = (await interrupt.boundingBox())!
  const options = (await toolbar.getByTestId('composer-options').boundingBox())!
  expect(Math.abs(stop.y - send.y)).toBeLessThan(2)
  expect(options.height).toBeLessThan(45)
})

test('o cabeçalho agrupa Marcar, Finalizar e Descartar em ordem, e o Marcar abre o popover', async ({ page }) => {
  await openWithDetails(page)
  const group = page.getByTestId('header-actions-group')
  await expect(group).toHaveAttribute('role', 'group')
  await expect(group).toHaveAccessibleName('Ações da conversa')
  const buttons = group.getByRole('button')
  await expect(buttons).toHaveCount(3)
  await expect(buttons.nth(0)).toHaveText('Marcar')
  await expect(buttons.nth(1)).toHaveText(/Finalizar|Reabrir/)
  await expect(buttons.nth(2)).toHaveText('Descartar')

  await group.getByTestId('mark-button').click()
  await expect(group.getByTestId('mark-button')).toHaveAttribute('aria-expanded', 'true')
  await expect(page.getByRole('menu').first()).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(group.getByTestId('mark-button')).toHaveAttribute('aria-expanded', 'false')
})

test('"Próxima" mostra a quantidade de conversas aguardando numa bolinha', async ({ page }) => {
  // The seeded sessions are not "unread", so none asks for the user: the list marks the others as news.
  await page.route(/\/api\/(projects\/\d+\/)?sessions(\?.*)?$/, async (route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    const response = await route.fetch()
    const list = await response.json() as Record<string, unknown>[]
    await route.fulfill({ response, json: list.map((s) => ({ ...s, unread: true })) })
  })
  await openWithDetails(page)
  const next = page.getByRole('button', { name: /^Próxima conversa que aguarda você/ })
  await expect(next).toBeVisible()
  await expect(next).toContainText('Próxima')
  const count = next.getByTestId('next-count')
  await expect(count).toHaveText(/^\d+$/)
  expect(Number(await count.innerText())).toBeGreaterThan(0)
  await expect(next).toHaveAttribute('aria-keyshortcuts', 'n')
})

test('o botão dos Detalhes fica pressionado com o painel aberto e o cabeçalho não rola na horizontal em 1440 e 1024', async ({ page }) => {
  await openWithDetails(page)
  await expect(page.getByTestId('toggle-details').first()).toHaveAttribute('aria-pressed', 'true')
  await noHorizontalScroll(page)
  await page.setViewportSize({ width: 1024, height: 800 })
  await expect(page.getByTestId('header-actions-group')).toBeVisible()
  await noHorizontalScroll(page)

  await page.setViewportSize({ width: 1440, height: 900 })
  const toggle = page.getByTestId('toggle-details').first()
  await toggle.click()
  await expect(toggle).toHaveAttribute('aria-pressed', 'false')
})

test('a barra do turno navega com as setas e com [ e ]', async ({ page }) => {
  await stage(page, EXTRA_TURNS)
  await openWithDetails(page)
  const bar = page.getByTestId('turn-bar')
  await expect(bar).toBeVisible()
  const prev = bar.getByRole('button', { name: 'Turno anterior' })
  const next = bar.getByRole('button', { name: 'Próximo turno' })
  // The thread opens at its end, on the last turn.
  await expect(bar).toContainText('Turno 3 de 3')
  await expect(next).toBeDisabled()
  await prev.click()
  await expect(bar).toContainText('Turno 2 de 3')
  await page.keyboard.press('[')
  await expect(bar).toContainText('Turno 1 de 3')
  await expect(prev).toBeDisabled()

  await next.click()
  await expect(bar).toContainText('Turno 2 de 3')
  await expect(prev).toBeEnabled()
  await page.keyboard.press(']')
  await expect(bar).toContainText('Turno 3 de 3')
  await expect(next).toBeDisabled()
  await page.keyboard.press('[')
  await expect(bar).toContainText('Turno 2 de 3')
  await prev.click()
  await expect(bar).toContainText('Turno 1 de 3')
})

test('"Copiar" aparece ao passar o mouse sobre a resposta e copia o texto', async ({ page, context }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write'])
  await stage(page, EXTRA_TURNS)
  await openWithDetails(page)
  const answer = page.locator('[data-item-id="t3"]')
  const copy = answer.getByTestId('copy')
  await expect(copy).toHaveCSS('opacity', '0')
  await answer.scrollIntoViewIfNeeded()
  await answer.hover()
  await expect(copy).toHaveCSS('opacity', '1')
  await expect(copy).toHaveAccessibleName('Copiar resposta')
  await expect(copy).toContainText('Copiar')
  await expect(copy).toHaveCSS('border-top-width', '0px')
  await copy.click()
  await expect(answer.getByTestId('copy-status')).toHaveText('Copiado')
  await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe('Terceira resposta')
})

test('os avisos são texto sem caixa, e o de erro tem role=alert', async ({ page }) => {
  await stage(page, [
    notice('n1', 'info', 'Aviso informativo de teste'),
    notice('n2', 'warning', 'Aviso de alerta de teste'),
    notice('n3', 'error', 'Aviso de erro de teste'),
  ])
  await openWithDetails(page)
  for (const level of ['info', 'warning', 'error']) {
    const el = page.locator(`[data-level="${level}"]`).filter({ hasText: 'de teste' })
    await expect(el).toBeVisible()
    await expect(el).toHaveCSS('border-top-width', '0px')
    await expect(el).toHaveCSS('background-color', 'rgba(0, 0, 0, 0)')
  }
  await expect(page.getByRole('alert').filter({ hasText: 'Aviso de erro de teste' })).toBeVisible()
  await expect(page.locator('[data-level="info"]').filter({ hasText: 'de teste' })).not.toHaveAttribute('role', 'alert')
})
