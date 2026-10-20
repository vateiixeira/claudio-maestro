import type { Page } from '@playwright/test'
import { expect, test } from './fixtures'

// Visual, keyboard, narrow-width and finished-session coverage for the Remote Control chip. The
// backend is staged like in remote-control.e2e.ts: a socket the spec writes to and a PATCH it answers.

type Item = Record<string, unknown>
const BASE = { model: null, model_resolved: null, effort: null, permission_mode: 'default', effort_pending: false }
const URL = 'https://claude.ai/code/session_e2e'

async function stage(page: Page, opts: { finished?: boolean } = {}) {
  const server = {
    seq: 0,
    options: { remote_control: false, remote_control_state: 'off', remote_control_url: null as string | null, remote_control_error: null as string | null },
    patches: [] as Array<Record<string, unknown>>,
  }
  let socket: { send(message: string): void } | null = null
  await page.routeWebSocket(/\/ws$/, (ws) => { socket = ws })
  if (opts.finished) {
    await page.route(/\/api\/projects\/\d+\/sessions$/, async (route) => {
      const response = await route.fetch()
      const list = (await response.json()) as Item[]
      await route.fulfill({ response, json: list.map((s) => ({ ...s, finished: true, display_state: 'finished' })) })
    })
  }
  await page.route(/\/api\/sessions\/[0-9a-f-]+$/, async (route) => {
    const method = route.request().method()
    if (method === 'GET') {
      const response = await route.fetch()
      const snapshot = await response.json()
      await route.fulfill({ response, json: { ...snapshot, seq: server.seq, ...server.options } })
      return
    }
    if (method !== 'PATCH') return route.fallback()
    const body = route.request().postDataJSON() as Record<string, unknown>
    server.patches.push(body)
    if (typeof body.remote_control === 'boolean') {
      server.options = body.remote_control
        ? { remote_control: true, remote_control_state: 'connecting', remote_control_url: null, remote_control_error: null }
        : { remote_control: false, remote_control_state: 'off', remote_control_url: null, remote_control_error: null }
    }
    await route.fulfill({ json: { ...BASE, ...server.options } })
  })
  await page.goto('/sessions')
  await page.getByText('Explique a estrutura do projeto').first().click()
  const sessionId = page.url().match(/[0-9a-f]{8}-[0-9a-f-]{27}/)?.[0] ?? ''
  return {
    server,
    async options(remote_control: boolean, state: string, url: string | null = null, error: string | null = null) {
      await expect.poll(() => socket !== null).toBe(true)
      server.options = { remote_control, remote_control_state: state, remote_control_url: url, remote_control_error: error }
      server.seq += 1
      socket!.send(JSON.stringify({ session_id: sessionId, seq: server.seq, type: 'session.options', data: { ...BASE, ...server.options } }))
    },
  }
}

const chip = (page: Page) => page.getByTestId('remote-control-chip')

test('o chip é o primeiro item da barra, antes do modelo', async ({ page }) => {
  await stage(page)
  await expect(chip(page)).toBeVisible()
  const bar = chip(page).locator('xpath=ancestor::div[contains(@class,"flex-wrap")][1]')
  await expect(bar.locator('button').first()).toHaveAttribute('data-test', 'remote-control-chip')
})

test('remote_control ligado com estado off aparece como conectando, sem azul', async ({ page }) => {
  const rc = await stage(page)
  await expect(chip(page)).toBeVisible()
  await rc.options(true, 'off')
  await expect(chip(page)).toHaveAttribute('data-state', 'connecting')
  await expect(chip(page)).not.toHaveClass(/text-info-soft/)
})

test('elsewhere mostra o aviso e o menu só tem Desligar', async ({ page }) => {
  const rc = await stage(page)
  await expect(chip(page)).toBeVisible()
  await rc.options(true, 'elsewhere')
  await expect(chip(page)).toHaveAttribute('data-state', 'elsewhere')
  await expect(chip(page)).toHaveAttribute('title', 'Remote Control pausado: a conversa está aberta em outro lugar')
  await chip(page).click()
  await expect(page.getByRole('menuitem')).toHaveText(['Desligar'])
})

test('o fundo azul aparece de fato quando ligado', async ({ page }) => {
  const rc = await stage(page)
  await expect(chip(page)).toBeVisible()
  const bg = () => chip(page).evaluate((el) => getComputedStyle(el).backgroundColor)
  const off = await bg()
  await rc.options(true, 'on', URL)
  await expect(chip(page)).toHaveAttribute('data-state', 'on')
  await expect.poll(bg).not.toBe(off)
  expect(await bg()).not.toMatch(/rgba\(0, 0, 0, 0\)|transparent/)
})

test('teclado: Enter e Espaço ligam, Esc fecha o menu e o foco volta ao chip', async ({ page }) => {
  const rc = await stage(page)
  await expect(chip(page)).toBeVisible()
  await chip(page).focus()
  await page.keyboard.press('Enter')
  await expect.poll(() => rc.server.patches).toEqual([{ remote_control: true }])
  await expect(chip(page)).toBeFocused()
  await rc.options(true, 'on', URL)
  await expect(chip(page)).toHaveAttribute('data-state', 'on') // Space on a chip still off would ask to turn it on again

  await page.keyboard.press('Space')
  const menu = page.getByRole('menu', { name: 'Remote Control' })
  await expect(menu).toBeVisible()
  await expect(menu.getByRole('menuitem').first()).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(menu).toHaveCount(0)
  await expect(chip(page)).toBeFocused()

  await page.keyboard.press('Enter')
  await page.keyboard.press('ArrowDown')
  await expect(menu.getByRole('menuitem', { name: 'Desligar' })).toBeFocused()
  await page.keyboard.press('Enter')
  await expect.poll(() => rc.server.patches).toEqual([{ remote_control: true }, { remote_control: false }])
  await expect(chip(page)).toBeFocused()
})

test('sessão concluída: chip desabilitado com o aviso e nenhum PATCH', async ({ page }) => {
  const rc = await stage(page, { finished: true })
  await expect(chip(page)).toBeVisible()
  await expect(chip(page)).toBeDisabled()
  await expect(chip(page)).toHaveAttribute('title', 'Reabra a sessão para ligar o Remote Control')
  await chip(page).click({ force: true })
  expect(rc.server.patches).toEqual([])
})

test('barra em largura reduzida (800px): nada transborda e o menu cabe na tela', async ({ page }) => {
  const rc = await stage(page)
  await page.setViewportSize({ width: 800, height: 700 })
  await expect(chip(page)).toBeVisible()
  await rc.options(true, 'on', URL)
  await expect(chip(page)).toHaveAttribute('data-state', 'on')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  const box = await chip(page).boundingBox()
  expect(box!.x).toBeGreaterThanOrEqual(0)
  expect(box!.x + box!.width).toBeLessThanOrEqual(800)
  await chip(page).click()
  const m = await page.getByRole('menu', { name: 'Remote Control' }).boundingBox()
  expect(m!.x).toBeGreaterThanOrEqual(0)
  expect(m!.x + m!.width).toBeLessThanOrEqual(800)
  await page.screenshot({ path: 'test-results/rc-narrow.png' })
})

for (const [id, label] of [['maestro', 'Maestro'], ['dracula', 'Dracula'], ['monokai-ristretto', 'Monokai Ristretto'], ['monokai-classic', 'Monokai Classic']] as const) {
  test(`tema ${label}: o chip ligado tem fundo e cor distintos do desligado`, async ({ page }) => {
    await page.goto('/preferencias')
    await page.locator('[data-test="theme-option"]', { hasText: label }).click()
    const rc = await stage(page)
    await expect(chip(page)).toBeVisible()
    const style = () => chip(page).evaluate((el) => { const s = getComputedStyle(el); return `${s.backgroundColor}|${s.color}|${s.borderColor}` })
    const off = await style()
    await rc.options(true, 'on', URL)
    await expect(chip(page)).toHaveAttribute('data-state', 'on')
    await expect.poll(style).not.toBe(off)
    expect(await chip(page).evaluate((el) => getComputedStyle(el).backgroundColor)).not.toBe('rgba(0, 0, 0, 0)')
    await page.screenshot({ path: `test-results/rc-theme-${id}.png` })
  })
}
