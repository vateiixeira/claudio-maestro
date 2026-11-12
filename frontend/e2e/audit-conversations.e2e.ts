import { expect, test } from './fixtures'

test('conversas do projeto separam título e resumo em telas largas e estreitas', async ({ page, request }) => {
  const response = await request.get('/api/projects', { headers: { 'X-Maestro': '1' } })
  const project = (await response.json() as { id: number; name: string }[]).find(item => item.name === 'Loja Demo')!
  await page.goto(`/projects/${project.id}?visao=conversas`)
  const rows = page.getByTestId('project-conversations').getByTestId('conversation-row')
  await expect(rows.first()).toBeVisible()
  for (const width of [360, 768, 1280]) {
    await page.setViewportSize({ width, height: 900 })
    const row = rows.first()
    const title = (await row.getByTestId('row-link').boundingBox())!
    const details = (await row.getByTestId('row-details').boundingBox())!
    expect(details.y).toBeGreaterThanOrEqual(title.y + title.height)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await expect(row.getByTestId('row-link')).toHaveAttribute('href', /sessao=|\/sessions\//)
  }
})
