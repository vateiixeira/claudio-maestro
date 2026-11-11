import { expect, test } from './fixtures'

// The built-in "Sem projeto" (kind "scratch") exists in every database. The server cannot remove
// it or its conversations, so the spec creates one conversation and the others only read.
const SCRATCH = 'Sem projeto'
const PROMPT = 'Mande um oi sem projeto nenhum'

test('conversa sem projeto: criar, achar na barra lateral, tela reduzida e detalhes', async ({ page, baseURL }) => {
  const headers = { 'X-Maestro': '1', Origin: baseURL! }
  const listed = await page.request.get('/api/projects', { headers })
  expect(listed.status()).toBe(200)
  const all = (await listed.json()) as { id: number; name: string; kind: string; available: boolean }[]
  const scratch = all.find((p) => p.kind === 'scratch')!
  expect(scratch.name).toBe(SCRATCH)
  expect(scratch.available).toBe(true)
  expect(all[all.length - 1].id, 'o embutido é o último da lista').toBe(scratch.id)

  await page.goto('/inbox')
  await expect(page.getByRole('heading', { name: 'Inbox', level: 1 })).toBeVisible()
  const sidebar = page.getByRole('navigation', { name: 'Navegação' })
  // Without any conversation it sits among the other projects, not in "Em andamento".
  await expect(sidebar.getByTestId('project').filter({ hasText: SCRATCH })).toHaveCount(0)
  const othersToggle = sidebar.getByTestId('others-toggle')
  if ((await othersToggle.getAttribute('aria-expanded')) !== 'true') await othersToggle.click()
  await expect(sidebar.getByTestId('other-project-name').last()).toHaveText(SCRATCH)

  // Focusing the composer loads the command catalog through an agent, which this server refuses.
  await page.route(/\/api\/(?:projects\/\d+|sessions\/[0-9a-f-]+)\/commands$/, (route) =>
    route.fulfill({ json: [] }),
  )

  await page.getByTestId('nav-new').click()
  const modal = page.getByTestId('new-conversation-modal')
  const options = modal.getByTestId('nc-project').getByRole('option')
  await expect(options.last()).toHaveText(SCRATCH)
  await modal.getByTestId('nc-project').selectOption({ label: SCRATCH })
  await modal.getByTestId('nc-prompt').fill(PROMPT)
  await modal.getByRole('button', { name: 'Iniciar conversa' }).click()
  await expect(page).toHaveURL(/\/sessions\/[0-9a-f-]+$/)
  await expect(page.getByTestId('user-message')).toHaveText(PROMPT)
  await expect(page.getByTestId('turn-entry').getByText('Resposta de teste: ' + PROMPT)).toBeVisible()

  // In the sidebar: "Em andamento", and last in the section.
  const active = sidebar.getByRole('region', { name: 'Em andamento' })
  const names = active.getByTestId('project-name')
  await expect(names.last()).toHaveText(SCRATCH)
  await expect(active.getByTestId('project-session').filter({ hasText: PROMPT })).toHaveCount(1)

  // Details: no branch list, but the Terminal tab exists.
  const properties = page.getByTestId('details-properties')
  if (!(await properties.isVisible())) await page.getByTestId('toggle-details').first().click()
  await expect(page.getByTestId('prop-project')).toContainText(SCRATCH)
  await expect(page.getByTestId('prop-branch-toggle')).toHaveCount(0)
  await expect(page.getByTestId('prop-branch-more')).toHaveCount(0)
  await expect(page.getByTestId('details-tab-terminal')).toBeVisible()

  // The reduced project screen.
  await active.getByTestId('project').filter({ hasText: SCRATCH }).getByTestId('project-name').click()
  await expect(page).toHaveURL(new RegExp(`/projects/${scratch.id}$`))
  const pane = page.getByTestId('project-pane')
  await expect(pane.getByRole('heading', { name: SCRATCH, level: 1 })).toBeVisible()
  await expect(pane.getByText(PROMPT)).toBeVisible()
  const newSession = pane.getByTestId('new-session')
  await expect(newSession).toBeEnabled()
  for (const id of ['open-organization', 'open-editor', 'rename', 'remove', 'sync', 'repos']) {
    await expect(pane.getByTestId(id), id).toHaveCount(0)
  }
  await expect(pane.getByText(/maestro-e2e/)).toHaveCount(0)
  await expect(pane.getByText('sem repositório git')).toHaveCount(0)

  // It stays out of the lists that are about registered projects.
  await page.goto('/projects')
  await expect(page.getByRole('main').getByText(SCRATCH, { exact: true })).toHaveCount(0)
  await page.goto('/agentes')
  await expect(page.getByRole('main').getByText(SCRATCH, { exact: true })).toHaveCount(0)
})
