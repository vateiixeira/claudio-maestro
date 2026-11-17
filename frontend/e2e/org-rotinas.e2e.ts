import { expect, test } from './fixtures'
import { expectNoHorizontalScroll, openOrganization, taskRow } from './org-helpers'

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
  await expect(row.getByTestId('routine-agent-name')).toHaveText('agente Triagem')
  await expect(row.getByRole('switch', { name: 'Rotina Triagem' })).toBeChecked()
  await expect(row.getByTestId('routine-creates-task')).toContainText('Cria tarefa')
  await expect(row.getByTestId('routine-schedules')).toHaveText(/^De segunda a sexta às \d{2}:\d{2}$/)
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

test('a chave da rotina liga e desliga sem trocar de tela', async ({ page }) => {
  const row = await openRoutines(page)
  const toggle = row.getByRole('switch', { name: 'Rotina Triagem' })
  await expect(toggle).toBeChecked()
  try {
    await toggle.click()
    await expect(toggle).not.toBeChecked()
    // The change was saved: it survives a reload.
    await page.reload()
    await page.getByTestId('org-tab-rotinas').click()
    await expect(page.getByTestId('routine-row').filter({ hasText: 'Triagem' }).getByRole('switch', { name: 'Rotina Triagem' })).not.toBeChecked()
  } finally {
    const again = page.getByTestId('routine-row').filter({ hasText: 'Triagem' }).getByRole('switch', { name: 'Rotina Triagem' })
    if ((await again.getAttribute('aria-checked')) === 'false') await again.click()
  }
  await expect(page.getByTestId('routine-row').filter({ hasText: 'Triagem' }).getByRole('switch', { name: 'Rotina Triagem' })).toBeChecked()
})

test('uma rotina nova mostra "sob demanda" e se exclui pelo menu', async ({ page }) => {
  await openRoutines(page)
  await page.getByTestId('routine-new').click()
  const form = page.getByTestId('routine-form')
  await form.getByTestId('routine-name').fill('Rotina descartável')
  await form.getByTestId('routine-agent').selectOption({ label: 'Revisor' })
  await form.getByTestId('routine-instruction').fill('Só para o teste do navegador.')
  await form.getByTestId('routine-enabled').uncheck()
  await form.getByTestId('routine-submit').click()
  await expect(page.getByTestId('routine-form')).toHaveCount(0)

  const row = page.getByTestId('routine-row').filter({ hasText: 'Rotina descartável' })
  await expect(row).toBeVisible()
  await expect(row.getByTestId('routine-agent-name')).toHaveText('agente Revisor')
  await expect(row.getByRole('switch', { name: 'Rotina Rotina descartável' })).not.toBeChecked()

  await row.getByRole('button', { name: 'Mais ações da rotina Rotina descartável' }).click()
  await page.getByRole('menuitem', { name: 'Excluir' }).click()
  await row.getByTestId('routine-delete-confirm').click()
  await expect(row).toHaveCount(0)
  await expect(page.getByTestId('routine-row').filter({ hasText: 'Triagem' })).toBeVisible()
})

test('a semana das rotinas aparece em tela larga e some em tela estreita', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  const row = await openRoutines(page)
  const week = page.getByTestId('routine-week')
  await expect(week).toBeVisible()
  await expect(week.getByTestId('routine-week-day')).toHaveCount(7)
  // Triagem fires Monday to Friday: five slots, one of them the next firing.
  await expect(week.getByTestId('routine-week-slot')).toHaveCount(5)
  await expect(week.locator('[data-test="routine-week-slot"][data-next="true"]')).toHaveCount(1)

  await page.setViewportSize({ width: 375, height: 800 })
  await expect(week).toBeHidden()
  await expect(row.getByTestId('routine-schedules')).toBeVisible()
  await expectNoHorizontalScroll(page)
})
