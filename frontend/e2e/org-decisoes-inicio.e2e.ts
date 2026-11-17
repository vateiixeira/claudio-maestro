import { expect, test } from './fixtures'
import { openOrganization, taskRow } from './org-helpers'

// The only spec that answers the decision of "Separar chamados urgentes". Everything it checks
// happens in one test, in the order a person would do it, so no other spec depends on the state.

const QUESTION = 'Responder em inglês ou português?'

test('a decisão pendente aparece no Início e na Inbox e some depois de respondida', async ({ page }) => {
  // The Inbox waits for the answer as well, in the tab of the conversations waiting for you.
  await page.goto('/inbox?aba=pede-voce')
  const inbox = page.getByTestId('inbox-decisions')
  await expect(inbox).toBeVisible()
  await expect(inbox.getByTestId('decision-card').filter({ hasText: QUESTION })).toBeVisible()

  await page.goto('/inicio')
  await expect(page.getByRole('heading', { level: 1, name: 'O que vamos resolver?' })).toBeVisible()
  const main = page.getByRole('main')
  const waiting = main.getByRole('region', { name: /Com você/ })
  const card = waiting.getByTestId('decision-card').filter({ hasText: QUESTION })
  await expect(card).toBeVisible()
  await expect(card.getByTestId('decision-option')).toHaveText(['Em português', 'Em inglês'])
  await expect(card.getByTestId('decision-submit')).toBeDisabled()
  // The tasks left the Início: no region of tasks, only what waits for you, what runs and what was delivered.
  await expect(main.getByRole('region', { name: 'Tarefas em andamento' })).toHaveCount(0)
  await expect(main.getByRole('region', { name: 'Concluídas recentes' })).toHaveCount(0)

  await card.getByTestId('decision-option').filter({ hasText: 'Em português' }).click()
  await expect(card.getByTestId('decision-option').filter({ hasText: 'Em português' })).toHaveAttribute('aria-pressed', 'true')
  await card.getByTestId('decision-submit').click()
  await expect(page.getByTestId('decision-card').filter({ hasText: QUESTION })).toHaveCount(0)

  await page.goto('/inbox?aba=pede-voce')
  await expect(page.getByRole('heading', { name: 'Inbox', level: 1 })).toBeVisible()
  await expect(page.getByTestId('inbox-decisions')).toHaveCount(0)

  // The task keeps the answer, with its receipt.
  await openOrganization(page)
  await taskRow(page, 'Separar chamados urgentes').click()
  const answered = page.getByRole('complementary').getByTestId('decision-card')
  await expect(answered).toHaveAttribute('data-status', 'answered')
  await expect(answered.getByTestId('decision-answer')).toHaveText('Em português')
  await expect(answered.getByTestId('decision-receipt')).toBeVisible()
})
