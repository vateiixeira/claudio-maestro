import type { Page } from '@playwright/test'
import { expect, test } from './fixtures'

// The seeded server has no Remote Control to connect, so the backend is staged: the snapshot of a
// seeded conversation carries the Remote Control fields, the PATCH is answered by the spec and the
// socket is replaced by one the spec writes to, like the backend would.

type Item = Record<string, unknown>

const BASE_OPTIONS = {
  model: null,
  model_resolved: null,
  effort: null,
  permission_mode: 'default',
  effort_pending: false,
}

async function stageRemoteControl(page: Page) {
  const server = {
    seq: 0,
    options: { remote_control: false, remote_control_state: 'off', remote_control_url: null as string | null, remote_control_error: null as string | null },
    items: [] as Item[],
    patches: [] as Array<Record<string, unknown>>,
  }
  let socket: { send(message: string): void } | null = null
  await page.routeWebSocket(/\/ws$/, (ws) => {
    socket = ws
  })
  await page.route(/\/api\/sessions\/[0-9a-f-]+$/, async (route) => {
    const method = route.request().method()
    if (method === 'GET') {
      const response = await route.fetch()
      const snapshot = await response.json()
      await route.fulfill({
        response,
        json: { ...snapshot, seq: server.seq, items: [...snapshot.items, ...server.items], ...server.options },
      })
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
    await route.fulfill({ json: { ...BASE_OPTIONS, ...server.options } })
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
    /** The backend reports a new state of the Remote Control. */
    async options(state: string, url: string | null = null, error: string | null = null) {
      server.options = { remote_control: true, remote_control_state: state, remote_control_url: url, remote_control_error: error }
      await push('session.options', { ...BASE_OPTIONS, ...server.options })
    },
    async upsert(item: Item) {
      server.items.push(item)
      await push('item.upsert', item)
    },
  }
}

const chip = (page: Page) => page.getByTestId('remote-control-chip')

test('o chip liga o Remote Control, fica azul, abre o menu e desliga', async ({ page }) => {
  const rc = await stageRemoteControl(page)

  await expect(chip(page)).toBeVisible()
  await expect(chip(page)).toHaveText('Remote Control')
  await expect(chip(page)).toHaveAttribute('data-state', 'off')
  await expect(chip(page)).toHaveAttribute('title', 'Ligar o Remote Control: a sessão aparece no app do Claude')

  await chip(page).click()
  await expect.poll(() => rc.server.patches).toEqual([{ remote_control: true }])
  await expect(chip(page)).toHaveAttribute('data-state', 'connecting')
  await expect(chip(page)).toHaveAttribute('title', 'Remote Control conectando…')

  await rc.options('on', 'https://claude.ai/code/session_e2e')
  await expect(chip(page)).toHaveAttribute('data-state', 'on')
  await expect(chip(page)).toHaveClass(/text-info-soft/)
  await expect(chip(page)).toHaveAttribute('title', 'Remote Control ativo · Clique para abrir no claude.ai ou desligar')

  await chip(page).click()
  const menu = page.getByRole('menu', { name: 'Remote Control' })
  await expect(menu.getByRole('menuitem')).toHaveText(['Abrir no claude.ai', 'Desligar'])
  const link = menu.getByRole('menuitem', { name: 'Abrir no claude.ai' })
  await expect(link).toHaveAttribute('href', 'https://claude.ai/code/session_e2e')
  await expect(link).toHaveAttribute('target', '_blank')
  await expect(link).toHaveAttribute('rel', 'noopener noreferrer')

  await menu.getByRole('menuitem', { name: 'Desligar' }).click()
  await expect.poll(() => rc.server.patches).toEqual([{ remote_control: true }, { remote_control: false }])
  await expect(menu).toHaveCount(0)
  await expect(chip(page)).toHaveAttribute('data-state', 'off')
  await expect(chip(page)).not.toHaveClass(/text-info-soft/)
})

test('o chip volta ligado depois de recarregar a página e mostra a falha sem azul', async ({ page }) => {
  const rc = await stageRemoteControl(page)
  await chip(page).click()
  await rc.options('failed', null, 'sem rede')
  await expect(chip(page)).toHaveAttribute('data-state', 'failed')
  await expect(chip(page)).toHaveAttribute('title', 'Remote Control não conectou: sem rede. Tentando de novo.')
  await expect(chip(page)).not.toHaveClass(/text-info-soft/)

  await rc.options('on', 'https://claude.ai/code/session_e2e')
  await page.reload()
  await expect(chip(page)).toHaveAttribute('data-state', 'on')
})

test('a mensagem vinda do celular aparece com a marca "via Remote Control"', async ({ page }) => {
  const rc = await stageRemoteControl(page)
  await expect(chip(page)).toBeVisible()

  await rc.upsert({ type: 'user', id: 'u-phone', text: 'Mensagem digitada no celular', remote: true, at: Math.floor(Date.now() / 1000) })
  const card = page.locator('[data-item-id="u-phone"]')
  await expect(card).toContainText('Mensagem digitada no celular')
  await expect(card.getByText('via Remote Control')).toBeVisible()
  await expect(card.getByText('via Remote Control')).toHaveAttribute('title', 'Enviada pelo Remote Control')

  // A message typed in the app has no mark.
  await rc.upsert({ type: 'user', id: 'u-app', text: 'Mensagem digitada aqui', at: Math.floor(Date.now() / 1000) })
  await expect(page.locator('[data-item-id="u-app"]')).toContainText('Mensagem digitada aqui')
  await expect(page.getByText('via Remote Control')).toHaveCount(1)
})
