import { expect, test } from './fixtures'

// A conversa do projeto "Painel Demo" com a frase no meio da resposta é o SCENARIO de scripts/e2e_server.py.
const TERM = 'tarefa automaticamente'

test('a busca acha uma frase dita no meio da conversa e abre na mensagem', async ({ page }) => {
  await page.goto('/sessions')
  const input = page.getByTestId('search-input')

  // O índice se enche em segundo plano logo depois da primeira sincronização: digita de novo até o trecho aparecer.
  await expect(async () => {
    await input.fill('')
    await input.fill(TERM)
    await expect(page.getByTestId('search-snippet').first()).toBeVisible({ timeout: 1500 })
  }).toPass({ timeout: 20_000 })

  const snippet = page.getByTestId('search-snippet').first()
  await expect(snippet.locator('mark')).toHaveText(TERM)
  await snippet.click()

  // O termo sai do endereço e a conversa abre rolada até a mensagem, destacada.
  await expect(page).toHaveURL(/\/sessions\/[0-9a-f-]+$/)
  const message = page.locator('[data-item-id][data-highlighted="true"]')
  await expect(message).toBeVisible()
  await expect(message).toContainText(TERM)
  await expect(message).toBeInViewport()
  // Não ficou no fim: a última resposta de enchimento está fora da tela. O texto também aparece
  // numa região só para leitores de tela, então a busca é feita dentro da conversa.
  await expect(page.getByTestId('turn-entry').getByText('Resposta de enchimento 20.')).not.toBeInViewport()
  await expect(page.getByTestId('jump-to-end')).toHaveCount(0)
})
