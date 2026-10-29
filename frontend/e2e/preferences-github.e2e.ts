import { expect, test } from './fixtures'

test('configurar o GitHub nas Preferências: salvar, recarregar e erro do servidor', async ({ page, consoleErrors }) => {
  await page.goto('/preferencias?aba=github')
  await expect(page.locator('[data-test="tab-github"]')).toHaveAttribute('aria-selected', 'true')
  // O servidor do E2E começa sem segredo.
  await expect(page.locator('[data-test="github-secret"]')).toBeVisible()

  await page.locator('[data-test="github-login"]').fill('vini-teste')
  await page.locator('[data-test="github-secret"]').fill('segredo-de-teste-com-20-chars')
  await page.locator('[data-test="github-save"]').click()
  await expect(page.getByText('Salvo', { exact: true })).toBeVisible()
  await expect(page.getByText('Segredo do webhook: definido')).toBeVisible()

  await page.reload()
  await expect(page.locator('[data-test="github-login"]')).toHaveValue('vini-teste')
  await expect(page.getByText('Segredo do webhook: definido')).toBeVisible()
  await expect(page.locator('[data-test="github-secret"]')).toHaveCount(0)

  await page.locator('[data-test="github-secret-change"]').click()
  await page.locator('[data-test="github-secret"]').fill('curto')
  await page.locator('[data-test="github-save"]').click()
  await expect(page.getByRole('alert')).toBeVisible()
  await expect(page.locator('[data-test="github-login"]')).toHaveValue('vini-teste')

  // The 422 the server answers on purpose is the only console error allowed.
  expect(consoleErrors.filter((m) => !m.includes('422'))).toEqual([])
  consoleErrors.length = 0
})
