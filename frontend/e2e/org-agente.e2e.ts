import { expect, test } from './fixtures'
import { expectNoHorizontalScroll, openAgent } from './org-helpers'

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
  await expect(page.getByTestId('memory-edit')).toBeVisible()
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

test('o interruptor do cabeçalho desliga o agente, avisa e volta ao ligar', async ({ page }) => {
  await openAgent(page, 'Revisor')
  const run = page.getByTestId('agent-run')
  const toggle = page.getByRole('switch', { name: 'Agente ligado' })
  const node = page.getByTestId('org-node-button').filter({ hasText: 'Revisor' })
  await expect(run).toBeEnabled()
  await expect(toggle).toBeChecked()
  await expect(page.getByTestId('agent-off')).toHaveCount(0)
  try {
    await toggle.click()
    await expect(toggle).not.toBeChecked()
    await expect(run).toBeDisabled()
    const warning = page.getByTestId('agent-off')
    await expect(warning).toContainText('Agente desligado.')
    await expect(node.getByTestId('agent-state')).toHaveAttribute('data-state', 'off')
    await expect(node.getByTestId('agent-state')).toHaveAccessibleName('Desligado')
    // The notice has its own button to turn the agent back on.
    await page.getByTestId('agent-off-enable').click()
    await expect(page.getByTestId('agent-off')).toHaveCount(0)
    await expect(toggle).toBeChecked()
    await toggle.click()
    await expect(toggle).not.toBeChecked()
  } finally {
    if ((await toggle.getAttribute('aria-checked')) === 'false') await toggle.click()
  }
  await expect(toggle).toBeChecked()
  await expect(run).toBeEnabled()
  await expect(node.getByTestId('agent-state')).toHaveAttribute('data-state', 'idle')
})

test('o menu do cabeçalho reúne as ações que mudam o agente e cada uma abre o seu diálogo', async ({ page }) => {
  await openAgent(page, 'Revisor')
  const header = page.getByTestId('agent-header')
  await expect(header.getByRole('heading', { level: 2, name: 'Revisor' })).toBeVisible()
  await expect(header.getByTestId('agent-boss-link')).toHaveText('Maestro')
  // Only "Rodar agora" and the switch stay in the open: the rest is in the menu.
  await expect(header.getByRole('button', { name: 'Rodar agora' })).toBeEnabled()
  await expect(page.getByTestId('agent-delete')).toHaveCount(0)

  const more = header.getByRole('button', { name: 'Mais ações do agente' })
  await more.click()
  const items = page.getByRole('menuitem')
  await expect(items).toHaveText(['Rodar com instrução…', 'Trocar chefe…', 'Duplicar para outro projeto…', 'Excluir…'])
  await page.getByRole('menuitem', { name: 'Rodar com instrução…' }).click()
  const run = page.getByRole('dialog', { name: 'Rodar com instrução' })
  await expect(run.getByTestId('agent-run-text')).toBeVisible()
  await run.getByTestId('confirm-cancel').click()
  await expect(run).toHaveCount(0)

  await more.click()
  await page.getByRole('menuitem', { name: 'Trocar chefe…' }).click()
  const boss = page.getByRole('dialog', { name: 'Trocar chefe' })
  await expect(boss.getByTestId('agent-boss')).toBeVisible()
  await boss.getByTestId('confirm-cancel').click()
  await expect(boss).toHaveCount(0)

  await more.click()
  await page.getByRole('menuitem', { name: 'Excluir…' }).click()
  const del = page.getByRole('dialog', { name: 'Excluir Revisor?' })
  await expect(del).toBeVisible()
  await del.getByTestId('confirm-cancel').click()
  await expect(del).toHaveCount(0)
  await expect(header.getByRole('heading', { level: 2, name: 'Revisor' })).toBeVisible()
})

test('o cabeçalho quebra de linha em tela estreita sem perder o menu nem rolar a página', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 800 })
  await openAgent(page, 'Triagem', 'definicao')
  const header = page.getByTestId('agent-header')
  for (const control of [
    header.getByRole('switch', { name: 'Agente ligado' }),
    header.getByRole('button', { name: 'Rodar agora' }),
    header.getByRole('button', { name: 'Mais ações do agente' }),
  ]) {
    await expect(control).toBeVisible()
    const box = (await control.boundingBox())!
    expect(box.x, 'dentro da tela').toBeGreaterThanOrEqual(0)
    expect(box.x + box.width, 'dentro da tela').toBeLessThanOrEqual(375)
  }
  await expectNoHorizontalScroll(page)
})

test('a Definição mostra "Como o agente roda" e o estado do cabeçalho', async ({ page }) => {
  await openAgent(page, 'Triagem', 'definicao')
  const status = page.getByTestId('definition-status')
  await expect(status).toContainText('Cabeçalho válido · sem alterações')
  await expect(page.getByTestId('definition-help')).toContainText('Cabeçalho entre as duas linhas')
  await expect(page.getByRole('heading', { name: 'Como o agente roda' })).toBeVisible()
  const fields = page.getByTestId('definition-fields')
  await expect(fields.getByTestId('definition-field').filter({ hasText: /^name/ }).getByTestId('definition-field-value')).toHaveText('Triagem')
  // What the header does not set shows the default value, marked as such.
  const model = fields.locator('[data-test="definition-field"][data-key="model"]')
  await expect(model.getByTestId('definition-field-value')).toHaveAttribute('data-default', 'true')
  await expect(model.getByTestId('definition-field-value')).toContainText('padrão')

  // Typing without saving changes the state; the text of the header is the one on the disk until saved.
  await page.getByTestId('definition-text').press('End')
  await page.getByTestId('definition-text').pressSequentially(' ')
  await expect(page.getByTestId('definition-status')).toHaveText('Alterações não salvas')
  await expect(page.getByTestId('definition-save')).toBeEnabled()
})

test('a Memória só abre o editor com Editar, salva o texto e mostra o medidor', async ({ page }) => {
  await openAgent(page, 'Revisor', 'memoria')
  const count = page.getByTestId('memory-count')
  await expect(page.getByTestId('memory-text')).toHaveCount(0)
  await expect(page.getByTestId('memory-meter')).toHaveAttribute('aria-valuemax', '4000')
  const note = 'Nota do E2E: o cliente prefere resposta curta.'
  try {
    await page.getByTestId('memory-edit').click()
    const area = page.getByTestId('memory-text')
    await expect(area).toBeVisible()
    await expect(page.getByTestId('memory-save')).toBeDisabled()
    await area.fill(note)
    await expect(page.getByTestId('memory-save')).toBeEnabled()
    // Cancel throws the draft away.
    await page.getByTestId('memory-cancel').click()
    await expect(page.getByTestId('memory-text')).toHaveCount(0)

    await page.getByTestId('memory-edit').click()
    await page.getByTestId('memory-text').fill(note)
    await page.getByTestId('memory-save').click()
    await expect(page.getByTestId('memory-text')).toHaveCount(0)
    await expect(page.getByTestId('memory-view')).toContainText(note)
    await expect(count).toContainText(`${note.length} de 4.000`)
    await expect(page.getByTestId('memory-meter')).toHaveAttribute('aria-valuenow', String(note.length))
    await page.reload()
    await expect(page.getByTestId('memory-view')).toContainText(note)
  } finally {
    // Leaves the memory empty, as the other specs and the seed expect.
    if (await page.getByTestId('memory-view').filter({ hasText: note }).count()) {
      await page.getByTestId('memory-edit').click()
      await page.getByTestId('memory-text').fill('')
      await page.getByTestId('memory-save').click()
    }
  }
  await expect(page.getByTestId('memory-empty')).toBeVisible()
  await expect(count).toContainText('0 de 4.000')
})
