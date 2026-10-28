import { expect, type Locator, type Page } from '@playwright/test'

// Shared steps of the org-*.e2e.ts specs. They only use what the person sees (links, rows, tabs),
// so no spec depends on the id the database gave to a project, agent or task.

export const PROJECT = 'Loja Demo'

/** The organization of a project, reached through the project picker. */
export async function openOrganization(page: Page, project = PROJECT): Promise<void> {
  await page.goto('/agentes')
  // Without a remembered project the picker shows; with one (an earlier visit in this page) the
  // address already has the project, and it may be another one.
  const option = page.getByTestId('org-project-option').filter({ hasText: project })
  const title = page.getByRole('heading', { level: 1, name: project })
  const select = page.getByTestId('org-project-select')
  await expect(option.or(title).or(select).first()).toBeVisible()
  if (await option.isVisible()) await option.click()
  else if (!(await title.isVisible())) await select.selectOption({ label: project })
  await expect(title).toBeVisible()
}

/** An agent's panel, opened from the tree. Returns the panel. */
export async function openAgent(page: Page, name: string, tab?: string): Promise<Locator> {
  await openOrganization(page)
  await page.getByTestId('org-node-button').filter({ hasText: name }).first().click()
  const panel = page.getByTestId('agent-panel')
  await expect(panel.getByRole('heading', { level: 2, name })).toBeVisible()
  if (tab) {
    await page.getByTestId(`agent-tab-${tab}`).click()
    await expect(page.getByTestId(`agent-tab-${tab}`)).toHaveAttribute('aria-selected', 'true')
  }
  return panel
}

/** A task's page, opened from the list of the project's open tasks. */
export async function openTask(page: Page, title: string): Promise<void> {
  await openOrganization(page)
  await page.getByTestId('task-row').filter({ hasText: title }).click()
  await expect(page.getByRole('heading', { level: 1 })).toContainText(title)
}

/** The row of the list of tasks with this title. */
export function taskRow(page: Page, title: string): Locator {
  return page.getByTestId('task-row').filter({ hasText: title })
}

/** No horizontal scroll on the page. */
export async function expectNoHorizontalScroll(page: Page): Promise<void> {
  const layout = await page.evaluate(() => ({ viewport: innerWidth, page: document.documentElement.scrollWidth }))
  expect(layout.page, 'largura da página').toBeLessThanOrEqual(layout.viewport + 1)
}
