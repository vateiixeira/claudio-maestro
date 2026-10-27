import { expect, test, openNavigationGroup } from './fixtures'

// The sidebar "Agentes" section and the agent's main conversation. Each test makes its own agent
// (and removes it afterwards), so the seeded "Triagem" and the other specs are left alone.
let counter = 0
const uniqueName = (prefix: string) => `${prefix} ${Date.now().toString(36)}${counter++}`

test.afterEach(async ({ page, baseURL }) => {
  const headers = { 'X-Maestro': '1', Origin: baseURL! }
  const list = await page.request.get('/api/specialists', { headers })
  for (const agent of (await list.json()) as { id: number; slug: string }[]) {
    if (agent.slug !== 'triagem') await page.request.delete(`/api/specialists/${agent.id}`, { headers })
  }
})

async function createAgent(page: import('@playwright/test').Page, baseURL: string, name: string) {
  const slug = name.toLowerCase().replace(/[^a-z0-9]+/g, '-')
  const response = await page.request.post('/api/specialists', {
    headers: { 'X-Maestro': '1', Origin: baseURL },
    data: { slug, name, project_id: 1 },
  })
  expect(response.ok()).toBeTruthy()
  return ((await response.json()) as { id: number }).id
}

test('abre a conversa principal pela barra lateral, com o link de configuração', async ({ page, baseURL }) => {
  const name = uniqueName('Revisor')
  const id = await createAgent(page, baseURL!, name)
  await page.goto('/inbox')
  await openNavigationGroup(page, 'Agentes e rotinas anteriores')
  const section = page.getByTestId('sidebar-agents')
  await expect(section.getByRole('heading', { name: 'Agentes' })).toBeVisible()
  const row = section.getByTestId('sidebar-agent-row').filter({ hasText: name })
  await expect(row).toBeVisible()
  await expect(row).not.toHaveAttribute('aria-current', 'page')

  await row.click()
  await expect(page).toHaveURL(/\/sessions\/[0-9a-f-]+$/)
  await expect(row).toHaveAttribute('aria-current', 'page')
  await expect(page.getByTestId('configure-agent')).toBeVisible()

  // The main conversation does not show up in the project's list.
  await expect(page.getByRole('navigation').getByRole('link', { name: new RegExp(name) })).toHaveCount(0)

  await page.getByTestId('configure-agent').click()
  await expect(page).toHaveURL(new RegExp(`/agentes/${id}\\?aba=settings$`))
  await expect(page.getByTestId('agent-name')).toHaveText(name)
  await expect(page.getByTestId('agent-tab-settings')).toHaveAttribute('aria-current', 'page')
})

test('outras conversas não têm o link "Configurar agente"', async ({ page }) => {
  await page.goto('/inbox')
  await page.getByRole('link', { name: /Explique a estrutura do projeto/ }).first().click()
  await expect(page).toHaveURL(/\/sessions\/[0-9a-f-]+$/)
  await expect(page.getByTestId('configure-agent')).toHaveCount(0)
})

test('agente desligado aparece marcado como desligado na barra lateral', async ({ page, baseURL }) => {
  const name = uniqueName('Pausado')
  const id = await createAgent(page, baseURL!, name)
  await page.goto(`/agentes/${id}`)
  await openNavigationGroup(page, 'Agentes e rotinas anteriores')
  const row = page.getByTestId('sidebar-agents').getByTestId('sidebar-agent-row').filter({ hasText: name })
  await expect(row).not.toContainText('desligado')
  await page.getByTestId('agent-enabled').click()
  await expect(row).toContainText('desligado')
  await expect(row).toBeVisible()
})
