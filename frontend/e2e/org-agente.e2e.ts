import { expect, test } from './fixtures'
import { openAgent } from './org-helpers'

// The panel of an agent. The edits that reach the disk (saving the AGENT.md) go to Triagem alone;
// Revisor takes the ones that are undone (a draft, turning off and on again).

test('um campo desconhecido no AGENT.md mostra o erro na linha e mantém o texto digitado', async ({ page, consoleErrors }) => {
  await openAgent(page, 'Revisor', 'definicao')
  const area = page.getByTestId('definition-text')
  await expect(area).toHaveValue(/name: Revisor/)
  const original = await area.inputValue()
  const typed = original.replace(/\n---\n/, '\ncor_favorita: azul\n---\n')
  expect(typed).not.toBe(original)
  await area.fill(typed)
  await expect(page.getByTestId('definition-save')).toBeEnabled()
  await page.getByTestId('definition-save').click()

  const error = page.getByTestId('definition-error')
  await expect(error).toBeVisible()
  await expect(error).toContainText('cor_favorita')
  await expect(error).toContainText(/linha \d+/)
  await expect(page.getByTestId('definition-goto')).toBeVisible()
  // What was typed is still there, unsaved.
  await expect(area).toHaveValue(typed)
  await expect(page.getByTestId('definition-save')).toBeEnabled()
  // The file on disk was not touched: reloading the page shows the original.
  await page.reload()
  await expect(page.getByTestId('definition-text')).toHaveValue(original)
  // The server refused the file with a 422, which the browser logs; nothing else may be logged.
  expect(consoleErrors.filter((m) => !m.includes('422'))).toEqual([])
  consoleErrors.length = 0
})

test('salvar um AGENT.md válido grava o arquivo', async ({ page }) => {
  await openAgent(page, 'Triagem', 'definicao')
  const area = page.getByTestId('definition-text')
  await expect(area).toHaveValue(/name: Triagem/)
  const note = 'Nota do E2E: responda sempre com cordialidade.'
  await area.fill(`${await area.inputValue()}\n${note}\n`)
  await expect(page.getByText('Alterações não salvas')).toBeVisible()
  await page.getByTestId('definition-save').click()
  await expect(page.getByText('Alterações não salvas')).toHaveCount(0)
  await expect(page.getByTestId('definition-save')).toBeDisabled()
  await expect(page.getByTestId('definition-error')).toHaveCount(0)
  await page.reload()
  await expect(page.getByTestId('definition-text')).toHaveValue(new RegExp(note))
})

test('o rascunho do AGENT.md sobrevive à troca de seção', async ({ page }) => {
  await openAgent(page, 'Revisor', 'definicao')
  const draft = 'Rascunho local que ainda não deve ser salvo'
  await page.getByTestId('definition-text').fill(draft)
  const tab = page.getByTestId('agent-tab-definicao')
  await expect(tab).toContainText('rascunho não salvo')
  await page.getByTestId('agent-tab-memoria').click()
  await expect(page.getByTestId('memory-text')).toBeVisible()
  await page.getByTestId('agent-tab-definicao').click()
  await expect(page.getByTestId('definition-text')).toHaveValue(draft)
})

test('as execuções filtram os problemas sem perder o histórico', async ({ page }) => {
  await openAgent(page, 'Triagem', 'execucoes')
  const rows = page.getByTestId('run-row')
  await expect(rows.filter({ hasText: 'O token do repositório expirou.' })).toHaveCount(1)
  await expect(page.getByTestId('run-outcome').filter({ hasText: 'Concluída' }).first()).toBeVisible()
  const all = await rows.count()

  await page.getByTestId('run-filter-problems').click()
  await expect(page.getByTestId('run-filter-problems')).toHaveAttribute('aria-pressed', 'true')
  await expect(rows.filter({ hasText: 'O token do repositório expirou.' })).toHaveCount(1)
  await expect(page.getByTestId('run-outcome').filter({ hasText: 'Falhou' }).first()).toBeVisible()
  await expect(page.getByTestId('run-outcome').filter({ hasText: 'Concluída' })).toHaveCount(0)
  expect(await rows.count()).toBeLessThan(all)

  await page.getByTestId('run-filter-all').click()
  await expect(page.getByTestId('run-outcome').filter({ hasText: 'Concluída' }).first()).toBeVisible()
})

test('Rodar agora fica indisponível com o agente desligado e volta ao ligar', async ({ page }) => {
  await openAgent(page, 'Revisor')
  const run = page.getByTestId('agent-run')
  const toggle = page.getByTestId('agent-toggle')
  const node = page.getByTestId('org-node-button').filter({ hasText: 'Revisor' })
  await expect(run).toBeEnabled()
  await expect(toggle).toHaveText('Desligar')
  try {
    await toggle.click()
    await expect(toggle).toHaveText('Ligar')
    await expect(run).toBeDisabled()
    await expect(page.getByTestId('agent-run-blocked')).toContainText('desligado')
    await expect(node.getByTestId('agent-state')).toHaveAttribute('data-state', 'off')
    await expect(node.getByTestId('agent-state')).toHaveAccessibleName('Desligado')
    await expect(page.getByTestId('agent-panel')).toContainText('Desligado')
  } finally {
    if ((await toggle.textContent())?.trim() === 'Ligar') await toggle.click()
  }
  await expect(toggle).toHaveText('Desligar')
  await expect(run).toBeEnabled()
  await expect(node.getByTestId('agent-state')).toHaveAttribute('data-state', 'idle')
})
