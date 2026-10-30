import { expect, test } from './fixtures'
import type { Page } from '@playwright/test'

// The backend of E2E cannot run an agent, so the run is staged: "Triagem" gets the long funnel conversation
// of "Painel Demo" as its main one, and `server` plays the backend, which holds the run in another seeded
// conversation. Events (`agent.run`, `session.state`) come through the intercepted WebSocket.

const MAIN_TITLE = 'Como configuro a jornada do funil?'
const RUN_TITLE = 'Resuma o último commit'
const OTHER_TITLE = 'Registre o código xilofone-arquivado no histórico antigo'

interface Server {
  outcome: string | null
  runState: string
  runSessionId: string
}

async function stage(page: Page, server: Server) {
  let socket: { send(message: string): void } | null = null
  await page.routeWebSocket(/\/ws$/, (ws) => {
    socket = ws
  })
  const headers = { 'X-Maestro': '1' }
  const agents = (await (await page.request.get('/api/agents', { headers })).json()) as Array<{ id: number; slug: string }>
  const triagemId = agents.find((a) => a.slug === 'triagem')!.id
  const ids: Record<string, string> = {}
  const projects = (await (await page.request.get('/api/projects', { headers })).json()) as Array<{ id: number; name: string }>
  const painel = projects.find((p) => p.name === 'Painel Demo')!
  const seeded = (await (await page.request.get(`/api/projects/${painel.id}/sessions`, { headers })).json()) as Array<{ session_id: string; title: string }>
  for (const s of seeded) ids[s.title] = s.session_id
  server.runSessionId = ids[RUN_TITLE]

  const run = () => ({
    id: 99,
    agent_id: triagemId,
    session_id: server.runSessionId,
    source: 'assignment',
    routine_id: null,
    scheduled_for: null,
    started_at: 1893371014,
    ended_at: server.outcome === 'running' || server.outcome === 'waiting' ? null : 1893371100,
    outcome: server.outcome,
    reason: null,
    task_id: null,
    commented: false,
    rewoken: false,
  })
  await page.route(/\/api\/agents(\/\d+)?(\?.*)?$/, async (route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    // The test may end with this request in flight, and the page is gone: nothing to answer then.
    const response = await route.fetch().catch(() => null)
    const body = response && (await response.json().catch(() => null))
    if (!response || body === null) return
    const patch = (agent: Record<string, unknown>) => {
      if (agent.slug !== 'triagem') return agent
      return { ...agent, main_session_id: ids[MAIN_TITLE], last_run: server.outcome ? run() : agent.last_run }
    }
    await route.fulfill({ response, json: Array.isArray(body) ? body.map(patch) : patch(body) })
  })
  await page.route(/\/api\/projects\/\d+\/sessions(\?.*)?$/, async (route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    const response = await route.fetch().catch(() => null)
    const list = response && ((await response.json().catch(() => null)) as Array<Record<string, unknown>> | null)
    if (!response || !list) return
    await route.fulfill({
      response,
      json: list.map((s) => {
        if (s.title === MAIN_TITLE) return { ...s, agent_id: triagemId }
        if (s.title === RUN_TITLE) return { ...s, agent_id: triagemId, state: server.runState }
        return s
      }),
    })
  })
  return {
    ids,
    run,
    send: async (type: string, data: unknown, sessionId = '') => {
      await expect.poll(() => socket !== null).toBe(true)
      socket!.send(JSON.stringify({ session_id: sessionId, seq: Math.floor(Math.random() * 1e6) + 1000, type, data }))
    },
  }
}

test('a faixa mostra o run em outra sessão, vira laranja, abre a sessão e some quando o run termina', async ({ page }) => {
  const server: Server = { outcome: 'running', runState: 'running', runSessionId: '' }
  const staged = await stage(page, server)
  await page.goto(`/sessions/${staged.ids[MAIN_TITLE]}`)

  const banner = page.getByTestId('agent-run-banner')
  await expect(banner).toBeVisible()
  await expect(banner).toHaveAttribute('data-state', 'running')
  await expect(banner).toContainText(`Rodando agora: ${RUN_TITLE}`)

  // The strip is outside the scroller: it does not move while the messages scroll.
  const before = await banner.boundingBox()
  await page.mouse.move(500, 400)
  await page.mouse.wheel(0, 3000)
  await expect(page.getByTestId('agent-run-banner')).toBeVisible()
  expect(await banner.boundingBox()).toEqual(before)

  // The session of the run waits for the user: orange and another text.
  server.outcome = 'waiting'
  server.runState = 'awaiting_decision'
  await staged.send('agent.run', staged.run())
  await expect(banner).toHaveAttribute('data-state', 'waiting')
  await expect(banner).toContainText(`${RUN_TITLE} espera sua resposta`)

  // Back to running, then the click takes to the session of the run.
  server.outcome = 'running'
  server.runState = 'running'
  await staged.send('agent.run', staged.run())
  await expect(banner).toHaveAttribute('data-state', 'running')
  await banner.click()
  await expect(page).toHaveURL(new RegExp(`/sessions/${staged.ids[RUN_TITLE]}$`))
  // The conversation of the run is not the main one of the agent: no strip there.
  await expect(page.getByTestId('agent-run-banner')).toHaveCount(0)

  // Back in the main conversation, the run ends: the strip goes away without a reload.
  await page.goBack()
  await expect(banner).toBeVisible()
  server.outcome = 'concluded'
  server.runState = 'idle'
  await staged.send('agent.run', staged.run())
  await staged.send('session.state', { state: 'idle', error: null }, staged.ids[RUN_TITLE])
  await expect(banner).toHaveCount(0)
})

test('a faixa some quando só o turno da sessão fecha, sem evento do run', async ({ page }) => {
  const server: Server = { outcome: null, runState: 'running', runSessionId: '' }
  const staged = await stage(page, server)
  await page.goto(`/sessions/${staged.ids[MAIN_TITLE]}`)
  const banner = page.getByTestId('agent-run-banner')
  await expect(banner).toContainText(`Rodando agora: ${RUN_TITLE}`)
  server.runState = 'idle'
  await staged.send('session.state', { state: 'idle', error: null }, staged.ids[RUN_TITLE])
  await expect(banner).toHaveCount(0)
})

test('a faixa não aparece numa conversa comum nem numa sessão que o agente não tem como principal', async ({ page }) => {
  const server: Server = { outcome: 'running', runState: 'running', runSessionId: '' }
  const staged = await stage(page, server)
  await page.goto(`/sessions/${staged.ids[OTHER_TITLE]}`)
  await expect(page.getByRole('heading', { level: 1, name: OTHER_TITLE })).toBeVisible()
  await expect(page.getByTestId('agent-run-banner')).toHaveCount(0)
})

test('a faixa cabe numa largura estreita sem rolagem horizontal', async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 700 })
  const server: Server = { outcome: 'waiting', runState: 'awaiting_decision', runSessionId: '' }
  const staged = await stage(page, server)
  await page.goto(`/sessions/${staged.ids[MAIN_TITLE]}`)
  const banner = page.getByTestId('agent-run-banner')
  await expect(banner).toHaveAttribute('data-state', 'waiting')
  const box = await banner.boundingBox()
  expect(box!.x + box!.width).toBeLessThanOrEqual(360)
  const layout = await page.evaluate(() => ({ viewport: innerWidth, page: document.documentElement.scrollWidth }))
  expect(layout.page).toBeLessThanOrEqual(layout.viewport + 1)
})
