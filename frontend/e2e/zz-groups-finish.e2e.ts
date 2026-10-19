import type { Page } from '@playwright/test'
import { expect, test } from './fixtures'

// Finishing a seeded conversation is not fully undone by reopening it (it leaves the "Sua vez"
// lists), so this spec runs last (the "zz-" prefix) and no other spec reads that conversation
// afterwards. The groups it makes are deleted in afterEach.
const A = 'Loja Demo'
const A_TITLE = 'Explique a estrutura do projeto'
const GROUP = 'Ativo'

test.afterEach(async ({ page, baseURL }) => {
  const headers = { 'X-Maestro': '1', Origin: baseURL! }
  const list = await page.request.get('/api/groups', { headers })
  for (const group of (await list.json()) as { id: number }[]) {
    await page.request.delete(`/api/groups/${group.id}`, { headers })
  }
})

const sidebar = (page: Page) => page.getByRole('navigation', { name: 'Navegação' })

test('finalizar a última conversa ativa de um agrupador o tira da barra lateral', async ({ page }) => {
  await page.goto('/inbox')
  await sidebar(page).getByTestId('project').filter({ hasText: A }).click()
  await page.getByTestId('group-new').click()
  await page.getByTestId('group-new-name').fill(GROUP)
  await page.getByTestId('group-new-name').press('Enter')
  await expect(page.getByTestId('group-section').filter({ hasText: GROUP })).toBeVisible()

  await page.goto('/sessions')
  await page.getByTestId('row-link').filter({ hasText: A_TITLE }).first().click()
  await expect(page).toHaveURL(/\/sessions\/[0-9a-f-]+/)
  const group = page.getByTestId('prop-group')
  if (!(await group.isVisible())) await page.getByTestId('toggle-details').first().click()
  await group.selectOption({ label: GROUP })
  await expect(group).toHaveValue(/\d+/)

  const nav = sidebar(page)
  await expect(nav.getByTestId('sidebar-group')).toHaveCount(1)

  await page.goto('/sessions')
  await page.getByTestId('row-link').filter({ hasText: A_TITLE }).first().hover()
  await page.getByRole('button', { name: `Finalizar ${A_TITLE}` }).click()
  await expect(nav.getByTestId('sidebar-group')).toHaveCount(0)
  await expect(nav.getByText(GROUP, { exact: true })).toHaveCount(0)
  // The project still has other open conversations, so its toggle stays.
  await expect(nav.getByRole('button', { name: `Recolher ${A}` })).toBeVisible()

  // The project screen keeps listing the group.
  await nav.getByTestId('project').filter({ hasText: A }).click()
  await expect(page.getByTestId('group-section').filter({ hasText: GROUP })).toBeVisible()
})
