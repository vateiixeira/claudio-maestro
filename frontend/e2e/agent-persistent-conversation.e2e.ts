import { expect, test, openNavigationGroup } from './fixtures'

for (const width of [1440, 1024]) {
  test(`mantém a conversa principal e mostra cada execução dentro dela em ${width}px`, async ({ page, baseURL }) => {
    await page.setViewportSize({ width, height: 1000 })
    const headers = { 'X-Maestro': '1', Origin: baseURL! }
    const response = await page.request.post('/api/specialists', { headers, data: { name: `Persistente ${width}`, slug: `persistente-${width}`, project_id: 1 } })
    expect(response.ok()).toBeTruthy()
    const agent = await response.json() as { id: number }
    try {
      const mainResponse = await page.request.post(`/api/specialists/${agent.id}/main`, { headers })
      const main = await mainResponse.json() as { session_id: string }
      await page.goto(`/sessions/${main.session_id}`)
      await expect(page.getByTestId('agent-executions')).toBeVisible()
      const runResponse = await page.request.post(`/api/specialists/${agent.id}/run`, { headers })
      expect(runResponse.ok()).toBeTruthy()
      const run = await runResponse.json() as { id: number; session_id: string }
      // A rodada chega pelo WebSocket enquanto a rota continua sendo a principal.
      const row = page.locator(`[data-test="agent-execution"][data-run-id="${run.id}"]`)
      await expect(row).toBeVisible()
      await expect(page).toHaveURL(new RegExp(`/sessions/${main.session_id}$`))
      const toggle = row.getByTestId('agent-execution-toggle')
      if (await toggle.getAttribute('aria-expanded') !== 'true') await toggle.click()
      await expect(row.getByTestId('agent-execution-detail')).toBeVisible()
      await expect(row.getByTestId('agent-execution-full')).toHaveAttribute('href', `/sessions/${run.session_id}`)
      await page.screenshot({ path: `/tmp/maestro-conversa-persistente-${width}.png`, fullPage: true })
      // O atalho é estável mesmo depois de nascer outra conversa para a rotina.
      await openNavigationGroup(page, 'Agentes e rotinas anteriores')
      await page.getByTestId('sidebar-agent-row').filter({ hasText: `Persistente ${width}` }).click()
      await expect(page).toHaveURL(new RegExp(`/sessions/${main.session_id}$`))
      await page.reload()
      await expect(page.locator(`[data-test="agent-execution"][data-run-id="${run.id}"]`)).toBeVisible()
      expect(await page.locator('[data-test="conversation-scroller"]').evaluate(el => el.scrollWidth - el.clientWidth)).toBeLessThanOrEqual(1)
    } finally {
      await page.request.delete(`/api/specialists/${agent.id}`, { headers })
    }
  })
}
