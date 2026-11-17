import { expect, test } from './fixtures'

test('conversas do projeto separam título e resumo em telas largas e estreitas', async ({ page, request }) => {
  const response = await request.get('/api/projects', { headers: { 'X-Maestro': '1' } })
  const project = (await response.json() as { id: number; name: string }[]).find(item => item.name === 'Loja Demo')!
  // The seeded conversations have no summary and no badge, so the details line would be empty (and hidden): the
  // list that reaches the page gets a summary on the way in (nothing is written to the server).
  await page.route(new RegExp(`/api/projects/${project.id}/sessions(\\?.*)?$`), async (route) => {
    const response = await route.fetch()
    const sessions = (await response.json()) as Record<string, unknown>[]
    for (const session of sessions) session.digest_short = 'Resumo curto da conversa, para ocupar a linha de baixo.'
    await route.fulfill({ response, json: sessions })
  })
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
