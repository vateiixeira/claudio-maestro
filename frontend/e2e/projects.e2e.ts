import { expect, test } from './fixtures'

test('a barra lateral lista os projetos semeados e abre a página do projeto', async ({ page }) => {
  await page.goto('/inbox')
  const nav = page.getByRole('navigation', { name: 'Navegação' })

  await expect(nav.getByRole('link', { name: /Loja Demo/ }).first()).toBeVisible()
  await expect(nav.getByRole('link', { name: /Painel Demo/ }).first()).toBeVisible()

  await nav.getByRole('link', { name: /Painel Demo/ }).first().click()
  await expect(page).toHaveURL(/\/projects\/\d+/)
  await expect(page.getByRole('heading', { name: 'Painel Demo', level: 1 })).toBeVisible()
})
