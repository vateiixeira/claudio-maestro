import { expect, test } from './fixtures'

test('a raiz leva à Inbox e a navegação lateral abre cada tela', async ({ page }) => {
  await page.goto('/')
  await expect(page).toHaveURL(/\/inbox$/)
  await expect(page.getByRole('heading', { name: 'Inbox', level: 1 })).toBeVisible()

  const nav = page.getByRole('navigation', { name: 'Navegação' })

  await nav.getByTestId('nav-dashboard').click()
  await expect(page).toHaveURL(/\/dashboard$/)
  await expect(page.getByRole('heading', { name: 'Dashboard', level: 1 })).toBeVisible()

  await nav.getByTestId('nav-conversations').click()
  await expect(page).toHaveURL(/\/sessions$/)
  await expect(page.getByRole('heading', { name: 'Conversas', level: 1 })).toBeVisible()

  await nav.getByTestId('nav-deliveries').click()
  await expect(page).toHaveURL(/\/entregas$/)
  await expect(page.getByLabel('Dia anterior')).toBeVisible()

  await nav.getByTestId('preferences').click()
  await expect(page).toHaveURL(/\/preferencias$/)
  await expect(page.getByRole('heading', { name: 'Preferências', level: 1 })).toBeVisible()
})
