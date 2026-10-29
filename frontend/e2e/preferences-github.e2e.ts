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

const SECRET = 'outro-segredo-de-teste-20-chars'

async function ensureSecretDefined(page: import('@playwright/test').Page) {
  const secret = page.locator('[data-test="github-secret"]')
  if (await secret.isVisible()) {
    await secret.fill(SECRET)
    await page.locator('[data-test="github-save"]').click()
  }
  await expect(page.getByText('Segredo do webhook: definido')).toBeVisible()
}

test('salvar só o login não envia o segredo e o segredo nunca aparece', async ({ page }) => {
  await page.goto('/preferencias?aba=github')
  await ensureSecretDefined(page)
  await expect(page.getByText(SECRET)).toHaveCount(0)

  const bodies: Record<string, unknown>[] = []
  await page.route('**/api/agents-github', (route) => {
    if (route.request().method() === 'PUT') bodies.push(route.request().postDataJSON())
    return route.continue()
  })
  await page.locator('[data-test="github-login"]').fill('  login-novo  ')
  await page.locator('[data-test="github-save"]').click()
  await expect(page.getByText('Salvo', { exact: true })).toBeVisible()
  expect(bodies).toHaveLength(1)
  expect(bodies[0]).toEqual({ login: 'login-novo' })
  await page.reload()
  await expect(page.locator('[data-test="github-login"]')).toHaveValue('login-novo')
  await expect(page.locator('body')).not.toContainText(SECRET)
})

test('segredo com espaço nas pontas é recusado sem ecoar a entrada', async ({ page, consoleErrors }) => {
  await page.goto('/preferencias?aba=github')
  await ensureSecretDefined(page)
  await page.locator('[data-test="github-secret-change"]').click()
  const bad = ' espacos-nas-pontas-com-mais-de-20 '
  await page.locator('[data-test="github-secret"]').fill(bad)
  await page.locator('[data-test="github-save"]').click()
  const alert = page.getByRole('alert')
  await expect(alert).toBeVisible()
  await expect(alert).not.toContainText('espacos-nas-pontas')
  await expect(page.locator('[data-test="github-secret"]')).toHaveValue(bad)
  await expect(page.getByText('Salvo', { exact: true })).toHaveCount(0)
  expect(consoleErrors.filter((m) => !m.includes('422'))).toEqual([])
  consoleErrors.length = 0
})

test('setas trocam de aba e a aba Etiquetas segue funcionando', async ({ page }) => {
  await page.goto('/preferencias?aba=github')
  await page.locator('[data-test="tab-github"]').focus()
  await page.keyboard.press('ArrowRight')
  await expect(page.locator('[data-test="tab-labels"]')).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(page.locator('[data-test="tab-labels"]')).toHaveAttribute('aria-selected', 'true')
  await expect(page.locator('[data-test="github-login"]')).toHaveCount(0)
  await page.keyboard.press('ArrowLeft')
  await expect(page.locator('[data-test="tab-github"]')).toBeFocused()
})
