import { expect, test } from './fixtures'

async function openNewConversation(page: import('@playwright/test').Page) {
  await page.route(/\/api\/(?:projects\/\d+|sessions\/[^/]+)\/commands$/, route => route.fulfill({ json: [] }))
  await page.goto('/inbox')
  await page.getByTestId('nav-new').click()
  await expect(page.getByTestId('new-conversation-modal')).toBeVisible()
}

test('nova conversa preserva o rascunho ao clicar fora e fecha com Esc ou X', async ({ page }) => {
  await openNewConversation(page)
  const modal = page.getByTestId('new-conversation-modal')
  const prompt = modal.getByTestId('nc-prompt')
  await prompt.fill('Texto que ainda estou preparando')
  await modal.locator('..').click({ position: { x: 5, y: 5 } })
  await expect(modal).toBeVisible()
  await expect(prompt).toHaveValue('Texto que ainda estou preparando')
  await page.keyboard.press('Escape')
  await expect(modal).toHaveCount(0)
  await page.getByTestId('nav-new').click()
  await expect(prompt).toHaveValue('Texto que ainda estou preparando')
  await modal.getByTestId('nc-close').click()
  await expect(modal).toHaveCount(0)
})

test('controles habilitados mostram cursor de clique e enviar vazio continua desabilitado', async ({ page }) => {
  await openNewConversation(page)
  const modal = page.getByTestId('new-conversation-modal')
  const submit = modal.getByTestId('nc-submit')
  await expect(submit).toBeDisabled()
  await expect(submit).not.toHaveCSS('cursor', 'pointer')
  await expect(modal.getByTestId('nc-close')).toHaveCSS('cursor', 'pointer')
  await expect(modal.getByTestId('nc-project')).toHaveCSS('cursor', 'pointer')
  await modal.getByTestId('nc-prompt').fill('Mensagem de teste sem enviar')
  await expect(submit).toBeEnabled()
  await expect(submit).toHaveCSS('cursor', 'pointer')
})
