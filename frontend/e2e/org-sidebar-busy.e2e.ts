import { expect, test } from './fixtures'

// The backend of E2E cannot run an agent, so the turn is staged: the list of sessions gives one seeded
// conversation to "Triagem" and `server` plays the backend, which counts the agent as `busy` while that
// session has an open turn and publishes nothing when the turn closes (only `session.state` arrives).

test('o ícone do agente na barra lateral volta a ocioso quando o turno de uma sessão dele fecha', async ({ page }) => {
  const server = { state: 'running' as string }
  let socket: { send(message: string): void } | null = null
  await page.routeWebSocket(/\/ws$/, (ws) => {
    socket = ws
  })
  const agents = (await (await page.request.get('/api/agents', { headers: { 'X-Maestro': '1' } })).json()) as Array<{ id: number; slug: string }>
  const triagemId = agents.find((a) => a.slug === 'triagem')!.id
  const sessionIds = new Set<string>()
  await page.route(/\/api\/agents(\/\d+)?(\?.*)?$/, async (route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    const response = await route.fetch()
    const body = await response.json()
    const busy = server.state === 'running'
    const patch = (agent: Record<string, unknown>) => {
      if (agent.slug !== 'triagem') return agent
      return { ...agent, busy }
    }
    await route.fulfill({ response, json: Array.isArray(body) ? body.map(patch) : patch(body) })
  })
  await page.route(/\/api\/projects\/\d+\/sessions(\?.*)?$/, async (route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    const response = await route.fetch()
    const list = (await response.json()) as Array<Record<string, unknown>>
    // Every conversation seeded belongs to Triagem for this spec, so it does not depend on which ones other specs left.
    for (const s of list) sessionIds.add(s.session_id as string)
    await route.fulfill({ response, json: list.map((s) => ({ ...s, agent_id: triagemId, state: server.state })) })
  })

  await page.goto('/inicio')
  const row = page.getByTestId('sidebar-agent-row').filter({ hasText: 'Triagem' })
  await expect(row.getByTestId('agent-state')).toHaveAttribute('data-state', 'busy')

  // The turn closes: the page is not reloaded and no agent event arrives, only the session state.
  server.state = 'idle'
  await expect.poll(() => socket !== null).toBe(true)
  expect(sessionIds.size).toBeGreaterThan(0)
  for (const id of sessionIds) {
    socket!.send(JSON.stringify({ session_id: id, seq: 1000, type: 'session.state', data: { state: 'idle', error: null } }))
  }
  await expect(row.getByTestId('agent-state')).toHaveAttribute('data-state', 'idle')
})
