import { expect, test, openNavigationGroup } from './fixtures'

test('a raiz leva ao Início e a navegação lateral abre cada tela', async ({ page }) => {
  await page.goto('/')
  await expect(page).toHaveURL(/\/inicio$/)
  await expect(page.getByRole('heading', { name: 'O que vamos resolver?', level: 1 })).toBeVisible()

  const nav = page.getByRole('navigation', { name: 'Navegação' })

  await openNavigationGroup(page, 'Mais ferramentas')
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
