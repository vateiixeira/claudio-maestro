import type { Page } from '@playwright/test'
import { expect, test } from './fixtures'

// The seeded conversations are all closed and read, so none "wants you" and none runs. To have something to filter,
// the lists of each project that reach the page are patched on the way in (nothing is written to the server): one conversation runs,
// two have news you have not seen.
const RUNNING = 'Liste as tarefas pendentes'
const UNREAD = ['Explique a estrutura do projeto', 'Resuma o último commit']
const QUIET = 'Como configuro a jornada do funil?'

async function patchSessions(page: Page) {
  await page.route(/\/api\/projects\/\d+\/sessions(\?.*)?$/, async (route) => {
    const response = await route.fetch()
    const sessions = (await response.json()) as Record<string, unknown>[]
    for (const session of sessions) {
      if (session.title === RUNNING) Object.assign(session, { display_state: 'running', state: 'running' })
      if (UNREAD.includes(session.title as string)) Object.assign(session, { display_state: 'waiting', unread: true })
    }
    await route.fulfill({ response, json: sessions })
  })
}

const sidebar = (page: Page) => page.getByRole('navigation', { name: 'Navegação' })
const rows = (page: Page) => sidebar(page).getByTestId('project-session')
const chip = (page: Page, filter: string) => sidebar(page).locator(`[data-test="sidebar-filter"][data-filter="${filter}"]`)

test('ligar e desligar "aguardando você" muda as conversas do menu', async ({ page }) => {
  await patchSessions(page)
  await page.goto('/inicio')
  await expect(chip(page, 'waiting')).toHaveText(/2 aguardando você/)
  await expect(chip(page, 'waiting')).toHaveAttribute('aria-pressed', 'false')
  await expect(rows(page).filter({ hasText: QUIET })).toBeVisible()
  const all = await rows(page).count()

  await chip(page, 'waiting').click()
  await expect(chip(page, 'waiting')).toHaveAttribute('aria-pressed', 'true')
  await expect(rows(page)).toHaveCount(2)
  for (const title of UNREAD) await expect(rows(page).filter({ hasText: title })).toBeVisible()
  await expect(rows(page).filter({ hasText: QUIET })).toHaveCount(0)
  await expect(rows(page).filter({ hasText: RUNNING })).toHaveCount(0)

  // Clicking the chip again turns the filter off and the whole list comes back.
  await chip(page, 'waiting').click()
  await expect(chip(page, 'waiting')).toHaveAttribute('aria-pressed', 'false')
  await expect(rows(page)).toHaveCount(all)
  await expect(rows(page).filter({ hasText: QUIET })).toBeVisible()
})

test('ligar e desligar "rodando" muda as conversas do menu, e um filtro troca pelo outro', async ({ page }) => {
  await patchSessions(page)
  await page.goto('/inicio')
  await expect(chip(page, 'running')).toHaveText(/1 rodando/)
  const all = await rows(page).count()

  await chip(page, 'running').click()
  await expect(chip(page, 'running')).toHaveAttribute('aria-pressed', 'true')
  await expect(rows(page)).toHaveCount(1)
  await expect(rows(page).first()).toContainText(RUNNING)

  // Only one filter is on at a time.
  await chip(page, 'waiting').click()
  await expect(chip(page, 'running')).toHaveAttribute('aria-pressed', 'false')
  await expect(chip(page, 'waiting')).toHaveAttribute('aria-pressed', 'true')
  await expect(rows(page)).toHaveCount(2)
  await expect(rows(page).filter({ hasText: RUNNING })).toHaveCount(0)

  await chip(page, 'waiting').click()
  await expect(rows(page)).toHaveCount(all)
})
