import { expect, test } from './fixtures'
import { openOrganization, openTask, taskRow } from './org-helpers'

// The tasks of "Loja Demo". "Rascunhar o guia de estilo" and "Liberar acesso ao painel" have nobody
// responsible, so changing them wakes no agent and no other spec sees it.

const URGENT = 'Separar chamados urgentes'
const REVIEW = 'Revisar resposta padrão'
const BLOCKED = 'Atualizar a base de respostas'
const DONE = 'Fechar chamados da semana'
const LOOSE = 'Rascunhar o guia de estilo'
const UNBLOCK = 'Liberar acesso ao painel'

test('a lista mostra as tarefas abertas e filtra por estado e por responsável', async ({ page }) => {
  await openOrganization(page)
  for (const title of [URGENT, REVIEW, BLOCKED]) await expect(taskRow(page, title)).toBeVisible()
  // "Open" is the default: a finished task only shows when its chip is turned on.
  await expect(taskRow(page, DONE)).toHaveCount(0)
  await expect(page.getByTestId('status-chip-done')).toHaveAttribute('aria-pressed', 'false')
  await page.getByTestId('status-chip-done').click()
  await expect(taskRow(page, DONE)).toBeVisible()
  await page.getByTestId('status-chip-done').click()
  await expect(taskRow(page, DONE)).toHaveCount(0)

  // Only the blocked ones.
  for (const status of ['todo', 'in_progress', 'in_review']) await page.getByTestId(`status-chip-${status}`).click()
  await expect(taskRow(page, BLOCKED)).toBeVisible()
  await expect(taskRow(page, UNBLOCK)).toBeVisible()
  await expect(taskRow(page, URGENT)).toHaveCount(0)
  await expect(taskRow(page, REVIEW)).toHaveCount(0)
  await expect(taskRow(page, BLOCKED).getByTestId('task-status')).toHaveAttribute('data-status', 'blocked')
  await expect(taskRow(page, BLOCKED).getByTestId('task-status')).toContainText('Bloqueada')

  // All open ones again, by who is responsible.
  for (const status of ['todo', 'in_progress', 'in_review']) await page.getByTestId(`status-chip-${status}`).click()
  await page.getByTestId('assignee-filter').selectOption({ label: 'Triagem' })
  await expect(taskRow(page, URGENT)).toBeVisible()
  await expect(taskRow(page, REVIEW)).toBeVisible()
  await expect(taskRow(page, LOOSE)).toHaveCount(0)
  await expect(taskRow(page, URGENT).getByTestId('task-row-assignee')).toHaveText('Triagem')
})

test('a tarefa em andamento mostra a conversa, a execução e a decisão', async ({ page }) => {
  await openTask(page, URGENT)
  await expect(page.getByTestId('task-status').first()).toHaveAttribute('data-status', 'in_progress')
  await expect(page.getByTestId('task-status-select')).toHaveValue('in_progress')
  await expect(page.getByTestId('task-priority')).toHaveValue('high')
  await expect(page.getByTestId('task-assignee').getByRole('option', { selected: true })).toHaveText('Triagem')
  await expect(page.getByTestId('task-description')).toContainText('cobrança em duplicidade')

  const thread = page.getByRole('list', { name: 'Comentários' })
  // Answering the decision (another spec) adds comments to this thread, so each one is found by its text.
  const comments = thread.getByTestId('task-comment')
  const human = comments.filter({ hasText: 'Priorize os chamados de cobrança em duplicidade.' })
  await expect(human).toBeVisible()
  await expect(human).toHaveAttribute('data-author', 'human')
  const agent = comments.filter({ hasText: 'Separei 3 chamados urgentes' })
  await expect(agent).toBeVisible()
  await expect(agent).toHaveAttribute('data-author', 'agent')
  await expect(agent.getByTestId('comment-author')).toHaveText('Triagem')
  const app = comments.filter({ hasText: 'Execução concluída' })
  await expect(app).toBeVisible()
  await expect(app).toHaveAttribute('data-author', 'app')

  // The run that worked on the task, and the decision it waits on (still there if it was answered).
  const run = page.getByTestId('run-row')
    .filter({ hasText: 'Concluída' })
    .filter({ has: page.getByTestId('run-source').filter({ hasText: 'Tarefa' }) })
    .first()
  await expect(run).toBeVisible()
  await expect(run.getByTestId('run-agent')).toHaveText('Triagem')
  await expect(run.getByTestId('run-source')).toHaveText('Tarefa')
  await expect(page.getByTestId('task-run-count')).toHaveText(/^\d+ de \d+$/)
  await expect(page.getByRole('complementary').getByTestId('decision-card')).toContainText('Responder em inglês ou português?')
})

test('comentar na tarefa põe o comentário na conversa', async ({ page }) => {
  await openTask(page, LOOSE)
  const text = 'Vamos seguir o tom do site: direto e sem gíria.'
  await page.getByTestId('task-composer-text').fill(text)
  await page.getByTestId('task-composer-submit').click()
  const comment = page.getByRole('list', { name: 'Comentários' }).getByTestId('task-comment').filter({ hasText: text })
  await expect(comment).toBeVisible()
  await expect(comment).toHaveAttribute('data-author', 'human')
  await expect(page.getByTestId('task-composer-text')).toHaveValue('')
})

test('mudar o estado pelo select atualiza a tarefa e a lista', async ({ page }) => {
  await openTask(page, LOOSE)
  await page.getByTestId('task-status-select').selectOption('in_progress')
  await expect(page.getByTestId('task-status').first()).toHaveAttribute('data-status', 'in_progress')
  await expect(page.getByTestId('task-status').first()).toContainText('Em andamento')
  await expect(page.getByTestId('task-error')).toHaveCount(0)
  const statusNote = page.getByRole('list', { name: 'Comentários' }).getByTestId('task-comment').filter({ hasText: 'in_progress' })
  await expect(statusNote).toBeVisible()
  await expect(statusNote).toHaveAttribute('data-author', 'app')
  await page.getByTestId('task-back').click()
  await expect(page.getByRole('heading', { level: 1, name: 'Tarefas' })).toBeVisible()
  await expect(page.getByTestId('status-chip-in_progress')).toBeVisible()
  await expect(taskRow(page, LOOSE).getByTestId('task-status')).toHaveAttribute('data-status', 'in_progress')
})

test('uma tarefa bloqueada mostra o motivo e destravar tira o bloqueio', async ({ page }) => {
  // Only reads the other blocked task.
  await openTask(page, BLOCKED)
  await expect(page.getByTestId('task-blocked-reason')).toContainText('Falta acesso ao repositório de respostas.')

  await openTask(page, UNBLOCK)
  await expect(page.getByTestId('task-blocked-reason')).toContainText('O painel pede um login que ninguém tem.')
  await page.getByTestId('task-unblock').click()
  await expect(page.getByTestId('task-blocked')).toHaveCount(0)
  // Nobody is responsible, so it goes back to "to do".
  await expect(page.getByTestId('task-status').first()).toHaveAttribute('data-status', 'todo')
  await expect(page.getByTestId('task-status-select')).toHaveValue('todo')
})

test('a tarefa em revisão mostra o revisor e leva ao agente', async ({ page }) => {
  await openTask(page, REVIEW)
  await expect(page.getByTestId('task-status').first()).toHaveAttribute('data-status', 'in_review')
  await expect(page.getByTestId('task-status').first()).toContainText('Em revisão')
  await expect(page.getByTestId('task-reviewer').getByRole('option', { selected: true })).toHaveText('Revisor')
  await expect(page.getByTestId('task-assignee').getByRole('option', { selected: true })).toHaveText('Triagem')
  await page.getByTestId('task-reviewer-link').click()
  await expect(page.getByTestId('agent-panel').getByRole('heading', { level: 2, name: 'Revisor' })).toBeVisible()
})
