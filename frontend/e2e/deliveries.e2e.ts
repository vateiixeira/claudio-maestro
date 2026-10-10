import { expect, test } from './fixtures'

test('a tela de entregas abre no dia de hoje, sem dia seguinte', async ({ page }) => {
  await page.goto('/entregas')

  await expect(page.getByTestId('prev-day')).toBeEnabled()
  await expect(page.getByTestId('next-day')).toBeDisabled()
})
