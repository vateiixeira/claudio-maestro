import { expect, test } from './fixtures'

test('a conversa principal mostra o anúncio pendente da execução', async ({ page }) => {
  await page.goto('/inbox')
  await page.getByTestId('sidebar-agents').getByTestId('sidebar-agent-row').filter({ hasText: 'Triagem' }).click()
  await expect(page).toHaveURL(/\/sessions\/[0-9a-f-]+$/)
  await expect(page.getByRole('region', { name: 'Anúncios das execuções' })).toContainText('Triagem concluída: 3 itens novos.')
  await expect(page.getByTestId('configure-agent')).toBeVisible()
  await page.reload()
  await expect(page.getByTestId('announcement-card')).toContainText('Triagem concluída: 3 itens novos.')
  const overlap = await page.getByTestId('header-strip').evaluate((strip) => {
    const badge = strip.querySelector('[data-test="agent-badge"]')!.getBoundingClientRect()
    const actions = strip.querySelector('[data-test="header-actions"]')!.getBoundingClientRect()
    return badge.right > actions.left && badge.bottom > actions.top && badge.top < actions.bottom
  })
  expect(overlap).toBe(false)
  await page.screenshot({ path: '/tmp/maestro-anuncios-agentes.png', fullPage: true })
})

test('configura o login e troca o segredo do GitHub sem mostrá-lo depois', async ({ page }) => {
  await page.goto('/agentes')
  await page.getByTestId('agents-github-open').click()
  await expect(page).toHaveURL(/github=1/)
  await page.getByTestId('github-login').fill('vini-teste')
  const change = page.getByTestId('github-secret-change')
  if (await change.isVisible()) await change.click()
  await page.getByTestId('github-secret').fill('segredo-apenas-do-servidor-descartavel')
  await page.getByRole('button', { name: 'Salvar', exact: true }).click()
  await expect(page.getByRole('status')).toHaveText('Salvo')
  await expect(page.getByTestId('github-secret')).toHaveCount(0)
  await page.reload()
  await expect(page.getByTestId('github-login')).toHaveValue('vini-teste')
  await expect(page.getByText('Segredo do webhook: definido')).toBeVisible()
  await page.getByTestId('github-secret-change').click()
  await expect(page.getByTestId('github-secret')).toHaveValue('')
})
