import { expect, test } from './fixtures'

// The conversation opened here is the one with subagents of the SCENARIO of scripts/e2e_server.py:
// three `Agent` calls in the same answer. The first subagent's transcript has the model id, the
// second only has the alias "haiku" in its meta file, the third has no model at all.
test('o chip de modelo de cada subagente vem do transcrito, do apelido ou fica de fora', async ({ page }) => {
  await page.goto('/sessions')
  await page.getByText('Investigue o módulo de pagamentos').first().click()
  await expect(page).toHaveURL(/\/sessions\/[0-9a-f-]+/)

  // The three subagents are the actions of one work block, which starts closed.
  const block = page.getByTestId('work-block')
  await expect(block.getByTestId('work-count')).toHaveText('3 ações')
  await block.getByTestId('work-block-toggle').click()
  const rows = block.getByTestId('work-row')
  await expect(rows).toHaveCount(3)

  const rowOf = (description: string) => rows.filter({ hasText: description })

  // Model id from the subagent's transcript, shown by name with the full id in the title.
  const sonnet = rowOf('Mapear as rotas').getByTestId('model-chip')
  await expect(sonnet).toHaveText('Sonnet 5.5')
  await expect(sonnet).toHaveAttribute('title', 'claude-sonnet-5-5')

  // Only the alias of the meta file: the chip shows it as it is.
  const haiku = rowOf('Ler os testes').getByTestId('model-chip')
  await expect(haiku).toHaveText('Haiku')
  await expect(haiku).toHaveAttribute('title', 'haiku')

  // No model anywhere: no chip.
  await expect(rowOf('Conferir a documentação')).toHaveCount(1)
  await expect(rowOf('Conferir a documentação').getByTestId('model-chip')).toHaveCount(0)
})
