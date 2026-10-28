import { expect, test } from './fixtures'
import { openOrganization, taskRow } from './org-helpers'

// The only spec that answers the decision of "Separar chamados urgentes". Everything it checks
// happens in one test, in the order a person would do it, so no other spec depends on the state.

const QUESTION = 'Responder em inglês ou português?'

test('a decisão pendente aparece no Início e na Inbox e some depois de respondida', async ({ page }) => {
  // The Inbox waits for the answer as well.
  await page.goto('/inbox')
  const inbox = page.getByTestId('inbox-decisions')
  await expect(inbox).toBeVisible()
  await expect(inbox.getByTestId('decision-card').filter({ hasText: QUESTION })).toBeVisible()

  await page.goto('/inicio')
  await expect(page.getByRole('heading', { level: 1, name: 'O que vamos resolver?' })).toBeVisible()
  const main = page.getByRole('main')
  const waiting = main.getByRole('region', { name: /Precisam de você/ })
  const card = waiting.getByTestId('decision-card').filter({ hasText: QUESTION })
  await expect(card).toBeVisible()
  await expect(card.getByTestId('decision-option')).toHaveText(['Em português', 'Em inglês'])
  await expect(card.getByTestId('decision-submit')).toBeDisabled()

  // What is under way: the tasks in progress, in review and blocked, by shape and word.
  const active = main.getByRole('region', { name: 'Em andamento' })
  await expect(active.getByTestId('start-task').filter({ hasText: 'Separar chamados urgentes' })).toContainText('Em andamento')
  await expect(active.getByTestId('start-task').filter({ hasText: 'Revisar resposta padrão' })).toContainText('Em revisão')
  await expect(active.getByTestId('start-task').filter({ hasText: 'Atualizar a base de respostas' })).toContainText('Bloqueada')
  const recent = main.getByRole('region', { name: 'Concluídas recentes' })
  await expect(recent.getByTestId('start-task').filter({ hasText: 'Fechar chamados da semana' })).toBeVisible()
  await expect(active.getByTestId('start-task').filter({ hasText: 'Fechar chamados da semana' })).toHaveCount(0)

  await card.getByTestId('decision-option').filter({ hasText: 'Em português' }).click()
  await expect(card.getByTestId('decision-option').filter({ hasText: 'Em português' })).toHaveAttribute('aria-pressed', 'true')
  await card.getByTestId('decision-submit').click()
  await expect(page.getByTestId('decision-card').filter({ hasText: QUESTION })).toHaveCount(0)

  await page.goto('/inbox')
  await expect(page.getByTestId('inbox-decisions')).toHaveCount(0)

  // The task keeps the answer, with its receipt.
  await openOrganization(page)
  await taskRow(page, 'Separar chamados urgentes').click()
  const answered = page.getByRole('complementary').getByTestId('decision-card')
  await expect(answered).toHaveAttribute('data-status', 'answered')
  await expect(answered.getByTestId('decision-answer')).toHaveText('Em português')
  await expect(answered.getByTestId('decision-receipt')).toBeVisible()
})
