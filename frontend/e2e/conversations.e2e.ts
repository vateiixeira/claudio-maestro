import { expect, test } from './fixtures'

// The texts below are the SCENARIO of scripts/e2e_server.py.
test('a lista de conversas mostra as conversas gravadas', async ({ page }) => {
  await page.goto('/sessions')

  await expect(page.getByText('Explique a estrutura do projeto').first()).toBeVisible()
  await expect(page.getByText('Liste as tarefas pendentes').first()).toBeVisible()
  await expect(page.getByText('Resuma o último commit').first()).toBeVisible()
})

test('abrir uma conversa gravada mostra a pergunta e a resposta', async ({ page }) => {
  await page.goto('/sessions')

  await page.getByText('Explique a estrutura do projeto').first().click()

  await expect(page).toHaveURL(/\/sessions\/[0-9a-f-]+/)
  // The sidebar and a screen-reader live region repeat these texts, so look inside the thread.
  await expect(
    page.getByTestId('user-message-row').getByText('Explique a estrutura do projeto'),
  ).toBeVisible()
  await expect(
    page.getByTestId('turn-entry').getByText('O projeto tem uma pasta src com o código da loja.'),
  ).toBeVisible()
})
