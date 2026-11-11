import { expect, test } from './fixtures'

test('agentes recolhidos deixam conversas visíveis e a expansão por teclado é preservada', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 720 })
  const mutations: string[] = []
  page.on('request', (request) => {
    if (request.method() !== 'GET' && /\/api\/(sessions|agents)\//.test(request.url())) mutations.push(request.url())
  })
  await page.goto('/inicio')
  const toggle = page.getByTestId('sidebar-agents-toggle')
  await expect(toggle).toHaveAttribute('aria-expanded', 'false')
  await expect(page.getByTestId('sidebar-agent-row')).toHaveCount(0)
  await expect(page.getByRole('heading', { name: 'Conversas abertas', exact: true })).toBeInViewport()
  await toggle.focus()
  await page.keyboard.press('Enter')
  await expect(toggle).toHaveAttribute('aria-expanded', 'true')
  await expect(page.getByTestId('sidebar-agent-row').first()).toBeVisible()
  const bounds = await page.locator('#sidebar-agents-list').boundingBox()
  expect(bounds!.height).toBeLessThanOrEqual(202)
  await page.reload()
  await expect(toggle).toHaveAttribute('aria-expanded', 'true')
  await toggle.focus()
  await page.keyboard.press('Space')
  await expect(toggle).toHaveAttribute('aria-expanded', 'false')
  expect(mutations).toEqual([])
})
