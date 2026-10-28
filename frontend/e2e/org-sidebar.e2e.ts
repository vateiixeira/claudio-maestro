import { expect, test } from './fixtures'

// The sidebar after the reorganization: "Agentes" in the navigation, no "CTO" entry, and the agents
// of each project under their own heading.

test('a navegação tem Agentes e não tem mais CTO', async ({ page }) => {
  await page.goto('/inicio')
  const nav = page.getByRole('navigation', { name: 'Navegação' })
  await expect(nav.getByTestId('nav-agents')).toHaveText(/Agentes/)
  await expect(nav.getByTestId('nav-agents')).toHaveAttribute('href', '/agentes')
  await expect(nav.getByRole('link', { name: /^CTO/ })).toHaveCount(0)
  await expect(nav.getByTestId('nav-tasks')).toHaveText(/Tarefas/)
  // The links in the "more tools" fold are there too, and none of them is the CTO.
  await expect(nav.getByRole('link', { includeHidden: true }).filter({ hasText: 'CTO' })).toHaveCount(0)
  await nav.getByTestId('nav-agents').click()
  await expect(page.getByTestId('nav-agents')).toHaveAttribute('aria-current', 'page')
})

test('a seção Agentes agrupa os agentes por projeto', async ({ page }) => {
  await page.goto('/inicio')
  const section = page.getByTestId('sidebar-agents')
  await expect(section.getByTestId('section-title')).toHaveText('Agentes')
  const project = section.getByTestId('sidebar-agent-project').filter({ hasText: 'Loja Demo' })
  await expect(project).toBeVisible()
  // The group of "Loja Demo" has its three agents, and "Painel Demo" has none, so no heading.
  const rows = section.getByTestId('sidebar-agent-row')
  for (const name of ['Maestro', 'Triagem', 'Revisor']) {
    await expect(rows.filter({ hasText: name }).getByTestId('sidebar-agent-name')).toHaveText(name)
  }
  await expect(section.getByTestId('sidebar-agent-project').filter({ hasText: 'Painel Demo' })).toHaveCount(0)
  await expect(rows.first().getByTestId('agent-state')).toBeVisible()
})

test('o contador de avisos de Agentes cai quando o aviso é lido na Inbox', async ({ page }) => {
  await page.goto('/inicio')
  const count = page.getByTestId('agents-count')
  // The number is exactly 1 (the count is spoken as "1 aviso não lido"), not 11 or 21.
  await expect(page.getByTestId('nav-agents')).toHaveAccessibleName('Agentes 1 aviso não lido')
  await expect(count.getByText('1', { exact: true })).toBeVisible()
  // Triagem is the one with the unread notice.
  await expect(page.getByTestId('sidebar-agent-row').filter({ hasText: 'Triagem' }).getByTestId('sidebar-agent-unseen')).toBeVisible()

  await page.goto('/inbox')
  const notice = page.getByTestId('agent-notice').filter({ hasText: 'A Triagem falhou nas últimas execuções.' })
  await expect(notice).toBeVisible()
  await notice.getByTestId('agent-notice-read').click()
  await expect(page.getByTestId('agent-notice')).toHaveCount(0)
  await expect(page.getByTestId('agents-count')).toHaveCount(0)
})
