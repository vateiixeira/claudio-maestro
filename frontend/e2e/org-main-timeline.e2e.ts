import { expect, test } from './fixtures'
import type { Page } from '@playwright/test'

// The backend of E2E cannot run an agent, so the runs are staged: "Triagem" gets the long funnel conversation
// of "Painel Demo" as its main one, `server.runs` is what the backend would answer for `/api/agents/:id/runs`,
// and events (`agent.run`, `session.state`) come through the intercepted WebSocket. The sessions of the runs
// are seeded conversations of the two projects.

const MAIN_TITLE = 'Como configuro a jornada do funil?'
const DONE_TITLE = 'Resuma o último commit'
const LIVE_TITLE = 'Liste as tarefas pendentes'
const SUMMARY = 'Triagem concluída: 3 chamados urgentes separados e o resto ficou na fila.'
const LIVE_SUMMARY = 'Terminei a revisão das tarefas e não sobrou nada pendente.'

interface RunRow {
  id: number
  agent_id: number
  session_id: string
  source: string
  routine_id: number | null
  scheduled_for: number | null
  started_at: number
  ended_at: number | null
  outcome: string
  reason: string | null
  task_id: number | null
  commented: boolean
  rewoken: boolean
  summary: string | null
}

interface Server {
  runs: RunRow[]
  /** state of the session of each run, by seeded title */
  states: Record<string, string>
}

async function stage(page: Page, server: Server) {
  let socket: { send(message: string): void } | null = null
  await page.routeWebSocket(/\/ws$/, (ws) => {
    socket = ws
  })
  const headers = { 'X-Maestro': '1' }
  const agents = (await (await page.request.get('/api/agents', { headers })).json()) as Array<{ id: number; slug: string }>
  const triagemId = agents.find((a) => a.slug === 'triagem')!.id
  const all = (await (await page.request.get('/api/sessions', { headers })).json()) as Array<{ session_id: string; title: string }>
  const ids: Record<string, string> = {}
  for (const s of all) ids[s.title] = s.session_id

  const run = (over: Partial<RunRow> & Pick<RunRow, 'id' | 'session_id' | 'outcome'>): RunRow => ({
    agent_id: triagemId,
    source: 'assignment',
    routine_id: null,
    scheduled_for: null,
    started_at: 1893371014,
    ended_at: over.outcome === 'running' || over.outcome === 'waiting' ? null : 1893371100,
    reason: null,
    task_id: null,
    commented: false,
    rewoken: false,
    summary: null,
    ...over,
  })
  const titleOf = (sessionId: string) => Object.keys(ids).find((t) => ids[t] === sessionId)!
  const last = () => server.runs.find((r) => r.outcome === 'running' || r.outcome === 'waiting') ?? server.runs[server.runs.length - 1]

  await page.route(/\/api\/agents\/\d+\/runs(\?.*)?$/, async (route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    await route.fulfill({ json: server.runs })
  })
  await page.route(/\/api\/agents(\/\d+)?(\?.*)?$/, async (route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    // The test may end with this request in flight, and the page is gone: nothing to answer then.
    const response = await route.fetch().catch(() => null)
    const body = response && (await response.json().catch(() => null))
    if (!response || body === null) return
    const patch = (agent: Record<string, unknown>) => {
      if (agent.slug !== 'triagem') return agent
      return { ...agent, main_session_id: ids[MAIN_TITLE], last_run: server.runs.length ? last() : agent.last_run }
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
        const state = server.states[s.title as string]
        return state ? { ...s, agent_id: triagemId, state } : s
      }),
    })
  })
  return {
    ids,
    run,
    titleOf,
    send: async (type: string, data: unknown, sessionId = '') => {
      await expect.poll(() => socket !== null).toBe(true)
      socket!.send(JSON.stringify({ session_id: sessionId, seq: Math.floor(Math.random() * 1e6) + 1000, type, data }))
    },
  }
}

test('a execução concluída vira uma entrada do chat com o resumo, sem a lista antiga nem cartões', async ({ page }) => {
  const server: Server = { runs: [], states: { [DONE_TITLE]: 'idle' } }
  const staged = await stage(page, server)
  server.runs = [staged.run({ id: 11, session_id: staged.ids[DONE_TITLE], outcome: 'concluded', summary: SUMMARY })]
  await page.goto(`/sessions/${staged.ids[MAIN_TITLE]}`)

  const entry = page.getByTestId('run-entry')
  await expect(entry).toHaveCount(1)
  await expect(entry).toHaveAttribute('data-run-session', staged.ids[DONE_TITLE])
  await expect(entry.getByTestId('run-entry-marker')).toContainText('Concluída')
  await expect(entry.getByTestId('run-entry-result')).toContainText(SUMMARY)
  await expect(page.getByTestId('main-runs')).toHaveCount(0)
  await expect(page.getByTestId('announcement-card')).toHaveCount(0)
  // The funnel conversation is still there, around the entry.
  await expect(page.getByText('Na jornada do funil você monta uma regra assim').first()).toBeAttached()
})

test('"Ver passo a passo" abre a conversa da execução ali mesmo, sem trocar de URL', async ({ page }) => {
  const server: Server = { runs: [], states: { [DONE_TITLE]: 'idle' } }
  const staged = await stage(page, server)
  server.runs = [staged.run({ id: 11, session_id: staged.ids[DONE_TITLE], outcome: 'concluded', summary: SUMMARY })]
  await page.goto(`/sessions/${staged.ids[MAIN_TITLE]}`)
  const url = page.url()

  const entry = page.getByTestId('run-entry')
  const toggle = entry.getByTestId('run-entry-steps-toggle')
  await expect(toggle).toHaveAttribute('aria-expanded', 'false')
  await expect(entry.getByTestId('run-steps')).toHaveCount(0)
  await toggle.click()
  await expect(toggle).toHaveAttribute('aria-expanded', 'true')
  await expect(entry.getByTestId('run-steps')).toContainText('O último commit ajusta o gráfico semanal.')
  expect(page.url()).toBe(url)

  await toggle.click()
  await expect(toggle).toHaveAttribute('aria-expanded', 'false')
  await expect(entry.getByTestId('run-steps')).toHaveCount(0)
})

test('"Abrir sozinha" leva à sessão da execução', async ({ page }) => {
  const server: Server = { runs: [], states: { [DONE_TITLE]: 'idle' } }
  const staged = await stage(page, server)
  server.runs = [staged.run({ id: 11, session_id: staged.ids[DONE_TITLE], outcome: 'concluded', summary: SUMMARY })]
  await page.goto(`/sessions/${staged.ids[MAIN_TITLE]}`)

  await page.getByTestId('run-entry-open').click()
  await expect(page).toHaveURL(new RegExp(`/sessions/${staged.ids[DONE_TITLE]}$`))
  await expect(page.getByRole('heading', { level: 1, name: DONE_TITLE })).toBeVisible()
  // The conversation of a run is an ordinary one: no entries of runs there.
  await expect(page.getByTestId('run-entry')).toHaveCount(0)
})

test('a execução em andamento fica no fim com a linha ao vivo e, ao concluir, mostra o resultado', async ({ page }) => {
  const server: Server = { runs: [], states: { [DONE_TITLE]: 'idle', [LIVE_TITLE]: 'running' } }
  const staged = await stage(page, server)
  server.runs = [
    staged.run({ id: 11, session_id: staged.ids[DONE_TITLE], outcome: 'concluded', summary: SUMMARY }),
    staged.run({ id: 12, session_id: staged.ids[LIVE_TITLE], outcome: 'running', started_at: 1893371200 }),
  ]
  await page.goto(`/sessions/${staged.ids[MAIN_TITLE]}`)

  const entries = page.getByTestId('run-entry')
  await expect(entries).toHaveCount(2)
  const live = entries.last()
  await expect(live).toHaveAttribute('data-run-id', '12')
  await expect(live.getByTestId('run-entry-live')).toBeVisible()
  await expect(live.getByTestId('run-entry-cancel')).toBeVisible()
  await expect(live.getByTestId('run-entry-marker')).toContainText('Rodando agora')
  await expect(live.getByTestId('run-entry-result')).toHaveCount(0)
  // Nothing of the live one leaks into the finished entry.
  await expect(entries.first().getByTestId('run-entry-live')).toHaveCount(0)

  server.runs[1] = staged.run({ id: 12, session_id: staged.ids[LIVE_TITLE], outcome: 'concluded', started_at: 1893371200, ended_at: 1893371300, summary: LIVE_SUMMARY })
  server.states[LIVE_TITLE] = 'idle'
  await staged.send('agent.run', server.runs[1])
  await staged.send('session.state', { state: 'idle', error: null }, staged.ids[LIVE_TITLE])
  await expect(live.getByTestId('run-entry-result')).toContainText(LIVE_SUMMARY)
  await expect(live.getByTestId('run-entry-live')).toHaveCount(0)
  await expect(live.getByTestId('run-entry-cancel')).toHaveCount(0)
  await expect(live.getByTestId('run-entry-marker')).toContainText('Concluída')
})

test('a faixa "Rodando agora" rola até a entrada da execução, na mesma URL', async ({ page }) => {
  const server: Server = { runs: [], states: { [LIVE_TITLE]: 'running' } }
  const staged = await stage(page, server)
  server.runs = [staged.run({ id: 12, session_id: staged.ids[LIVE_TITLE], outcome: 'running' })]
  await page.goto(`/sessions/${staged.ids[MAIN_TITLE]}`)
  const url = page.url()

  const banner = page.getByTestId('agent-run-banner')
  await expect(banner).toContainText(`Rodando agora: ${LIVE_TITLE}`)
  const entry = page.getByTestId('run-entry')
  await expect(entry).toHaveCount(1)
  // The conversation is long: it opens at the end, so scroll to the top first, away from the entry.
  await page.getByTestId('run-entry').evaluate((el) => {
    let node: HTMLElement | null = el.parentElement
    while (node && node.scrollHeight <= node.clientHeight) node = node.parentElement
    node?.scrollTo({ top: 0 })
  })
  await expect(entry).not.toBeInViewport()

  await banner.click()
  await expect(entry).toBeInViewport()
  expect(page.url()).toBe(url)
})

test('uma execução em espera faz o campo de mensagem responder a ela, e a resposta vai para a sessão dela', async ({ page }) => {
  const server: Server = { runs: [], states: { [LIVE_TITLE]: 'awaiting_decision' } }
  const staged = await stage(page, server)
  server.runs = [staged.run({ id: 12, session_id: staged.ids[LIVE_TITLE], outcome: 'waiting', source: 'routine' })]
  await page.route(/\/api\/sessions\/[0-9a-f-]+\/commands$/, (route) => route.fulfill({ json: [] }))
  await page.goto(`/sessions/${staged.ids[MAIN_TITLE]}`)

  const target = page.getByTestId('reply-target')
  await expect(target).toContainText('Respondendo à rotina das')
  await expect(page.getByTestId('run-entry-marker')).toContainText('Aguardando você')

  // The message goes to the session of the run, not to the main conversation.
  await page.route(/\/api\/sessions\/[0-9a-f-]+\/messages$/, (route) =>
    route.fulfill({ json: { send_started: true, state: 'running', external_activity: false } }),
  )
  const sent = page.waitForRequest((r) => r.method() === 'POST' && /\/messages$/.test(r.url()))
  await page.getByRole('combobox', { name: /mensagem/i }).or(page.getByPlaceholder('Mensagem (Ctrl+V cola imagens)')).first().fill('Pode seguir com a opção B')
  await page.keyboard.press('Enter')
  const request = await sent
  expect(request.url()).toContain(`/api/sessions/${staged.ids[LIVE_TITLE]}/messages`)
  expect(request.postDataJSON()).toMatchObject({ text: 'Pode seguir com a opção B' })

  // Back to talking with the agent.
  await target.getByTestId('reply-target-dismiss').click()
  await expect(target).toHaveCount(0)
})

test('o X do aviso devolve o campo ao agente e o aviso some quando a execução deixa de esperar', async ({ page }) => {
  const server: Server = { runs: [], states: { [LIVE_TITLE]: 'awaiting_decision' } }
  const staged = await stage(page, server)
  server.runs = [staged.run({ id: 12, session_id: staged.ids[LIVE_TITLE], outcome: 'waiting' })]
  await page.goto(`/sessions/${staged.ids[MAIN_TITLE]}`)
  const target = page.getByTestId('reply-target')
  await expect(target).toContainText('Respondendo à execução das')

  server.runs[0] = staged.run({ id: 12, session_id: staged.ids[LIVE_TITLE], outcome: 'running' })
  server.states[LIVE_TITLE] = 'running'
  await staged.send('agent.run', server.runs[0])
  await expect(target).toHaveCount(0)
})
