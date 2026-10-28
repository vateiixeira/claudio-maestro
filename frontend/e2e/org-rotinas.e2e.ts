import { expect, test } from './fixtures'
import { openOrganization, taskRow } from './org-helpers'

// The routine of Triagem: every firing opens a task. The edit and "run now" change it, so each
// test asserts only what it did itself.

async function openRoutines(page: import('@playwright/test').Page) {
  await openOrganization(page)
  await page.getByTestId('org-tab-rotinas').click()
  await expect(page.getByTestId('org-tab-rotinas')).toHaveAttribute('aria-selected', 'true')
  const row = page.getByTestId('routine-row').filter({ hasText: 'Triagem' })
  await expect(row).toBeVisible()
  return row
}

test('a lista mostra a rotina com o agente, o horário e o aviso de que cria tarefa', async ({ page }) => {
  const row = await openRoutines(page)
  await expect(row.getByTestId('routine-name-text')).toHaveText('Triagem')
  await expect(row.getByTestId('routine-agent-name')).toHaveText('Triagem')
  await expect(row.getByTestId('routine-state')).toContainText('Ligada')
  await expect(row.getByTestId('routine-creates-task')).toContainText('Cria tarefa')
  await expect(row.getByTestId('routine-schedules')).toContainText(/\d{2}:\d{2}/)
  await expect(row.getByTestId('routine-instruction-text')).toContainText('Faça a triagem dos chamados novos.')
  await expect(row.getByTestId('routine-next')).not.toBeEmpty()
})

test('editar o horário da rotina atualiza a lista', async ({ page }) => {
  const row = await openRoutines(page)
  await row.getByTestId('routine-edit').click()
  const form = page.getByTestId('routine-form')
  await expect(form.getByRole('heading', { name: 'Editar rotina' })).toBeVisible()
  await expect(form.getByTestId('routine-create-task')).toBeChecked()
  await expect(form.getByTestId('routine-agent')).toBeDisabled()
  await form.getByTestId('schedule-time').first().fill('05:45')
  await form.getByTestId('routine-submit').click()
  await expect(page.getByTestId('routine-form')).toHaveCount(0)
  await expect(row.getByTestId('routine-schedules')).toContainText('05:45')
  await page.reload()
  await page.getByTestId('org-tab-rotinas').click()
  await expect(page.getByTestId('routine-row').filter({ hasText: 'Triagem' }).getByTestId('routine-schedules')).toContainText('05:45')
})

test('Rodar agora cria uma tarefa nova que aparece na lista de tarefas', async ({ page }) => {
  const row = await openRoutines(page)
  await row.getByTestId('routine-run').click()
  const feedback = row.getByTestId('routine-feedback')
  await expect(feedback).toHaveText(/^Tarefa #\d+ criada\.$/)
  const id = /#(\d+)/.exec((await feedback.textContent()) ?? '')![1]!
  await page.getByTestId('org-tab-tarefas').click()
  const created = page.getByTestId('task-row').filter({ hasText: new RegExp(`#${id}(?!\\d)`) })
  await expect(created).toBeVisible()
  await expect(created).toHaveAttribute('data-task-id', id)
  await expect(created).toContainText('Triagem ·')
  await expect(created.getByTestId('task-row-assignee')).toHaveText('Triagem')
  await expect(taskRow(page, 'Separar chamados urgentes')).toBeVisible()
})
