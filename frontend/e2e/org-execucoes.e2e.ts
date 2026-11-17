import { expect, test } from './fixtures'
import { expectNoHorizontalScroll, openOrganization } from './org-helpers'

// The Execuções of "Loja Demo": Triagem has a concluded run with a report (and the routine's
// summary), one that failed, and a scheduled time the Maestro never fired. Other specs may add
// runs (waking an agent), so each test finds its run by what it says and never counts them all.

const REPORT = 'Triagem concluída: 3 chamados novos, 1 urgente.'
const FAILURE = 'O token do repositório expirou.'
const MISSED = 'O horário passou e o Maestro não disparou o agente.'

async function openRuns(page: import('@playwright/test').Page) {
  await openOrganization(page)
  await page.getByTestId('org-tab-execucoes').click()
  await expect(page.getByTestId('org-tab-execucoes')).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByTestId('runs-tab')).toBeVisible()
  return page.getByTestId('runs-tab')
}

const rowWith = (tab: import('@playwright/test').Locator, text: string) => tab.getByTestId('run-row').filter({ hasText: text })

test('as execuções vêm em grupos por dia, com a perdida e a que falhou à vista', async ({ page }) => {
  const tab = await openRuns(page)
  // Runs 2, 26 and 50 hours back never share a day.
  expect(await tab.getByTestId('run-day').count()).toBeGreaterThanOrEqual(3)
  await expect(tab.getByTestId('run-day-label').first()).not.toBeEmpty()
  await expect(tab.getByTestId('runs-summary')).toContainText(/perdida/)

  const failed = rowWith(tab, FAILURE)
  await expect(failed).toBeVisible()
  await expect(failed.getByTestId('run-agent')).toHaveText('Triagem')
  await expect(failed.getByRole('img', { name: 'Falhou' })).toBeVisible()
  await expect(failed.getByTestId('run-started')).toHaveText(/^\d{2}:\d{2}$/)

  // The missed time is a row of its own, with a dash and no duration.
  const missed = tab.locator('[data-test="run-row"]').filter({ has: page.getByRole('img', { name: 'Perdida' }) })
  await expect(missed.first()).toBeVisible()
  await expect(missed.first().getByTestId('run-outcome')).toHaveAttribute('data-shape', 'dash')
})

test('clicar numa linha abre o relato da execução e clicar de novo fecha', async ({ page }) => {
  const tab = await openRuns(page)
  const row = tab.getByTestId('run-row').filter({ has: page.getByTestId('run-headline').filter({ hasText: 'Triagem concluída: 3 chamados' }) })
  const toggle = row.getByTestId('run-toggle')
  await expect(toggle).toHaveAttribute('aria-expanded', 'false')
  await expect(row.getByTestId('run-details')).toHaveCount(0)

  await toggle.click()
  await expect(toggle).toHaveAttribute('aria-expanded', 'true')
  await expect(row.getByTestId('run-summary')).toHaveText(REPORT)
  await expect(row.getByTestId('run-source')).toHaveText('Rotina')

  await toggle.click()
  await expect(toggle).toHaveAttribute('aria-expanded', 'false')
  await expect(row.getByTestId('run-details')).toHaveCount(0)
})

test('"Só problemas" esconde as concluídas e deixa a que falhou e a perdida, que explica o motivo ao abrir', async ({ page }) => {
  const tab = await openRuns(page)
  const concluded = tab.getByTestId('run-row').filter({ has: page.getByTestId('run-headline').filter({ hasText: 'Triagem concluída: 3 chamados' }) })
  await expect(concluded).toBeVisible()

  const chip = tab.getByTestId('runs-filter-problems')
  await expect(chip).toHaveAttribute('aria-pressed', 'false')
  await chip.click()
  await expect(chip).toHaveAttribute('aria-pressed', 'true')
  await expect(concluded).toHaveCount(0)
  const failed = rowWith(tab, FAILURE)
  await expect(failed).toBeVisible()
  await expect(tab.getByRole('img', { name: 'Perdida' }).first()).toBeVisible()
  await expect(tab.getByRole('img', { name: 'Concluída' })).toHaveCount(0)

  // The reason is already the headline of the line; opening it adds where the run came from.
  await expect(failed.getByTestId('run-headline')).toHaveText(FAILURE)
  await failed.getByTestId('run-toggle').click()
  await expect(failed.getByTestId('run-source')).toHaveText('Rotina')

  // The missed run explains itself when opened.
  const missed = tab.locator('[data-test="run-row"]').filter({ has: page.getByRole('img', { name: 'Perdida' }) }).first()
  await missed.getByTestId('run-toggle').click()
  await expect(missed.getByTestId('run-reason')).toHaveText(MISSED)

  await chip.click()
  await expect(chip).toHaveAttribute('aria-pressed', 'false')
  await expect(concluded).toBeVisible()
})

test('o filtro por agente mostra só as execuções dele', async ({ page }) => {
  const tab = await openRuns(page)
  await tab.getByTestId('runs-agent-filter').selectOption({ label: 'Triagem' })
  await expect(rowWith(tab, FAILURE)).toBeVisible()
  await tab.getByTestId('runs-agent-filter').selectOption({ label: 'Maestro' })
  await expect(rowWith(tab, FAILURE)).toHaveCount(0)
})

test('em tela estreita cada execução ocupa linhas próprias e a página não rola de lado', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 800 })
  const tab = await openRuns(page)
  const failed = rowWith(tab, FAILURE)
  await expect(failed).toBeVisible()
  for (const part of ['run-agent', 'run-headline', 'run-started']) await expect(failed.getByTestId(part)).toBeVisible()
  await failed.getByTestId('run-toggle').click()
  await expect(failed.getByTestId('run-details')).toBeVisible()
  await expectNoHorizontalScroll(page)
})
