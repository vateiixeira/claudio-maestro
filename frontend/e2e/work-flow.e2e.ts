import { expect, test } from './fixtures'

test('objetivo, decisão humana, nova tentativa e revisão usam o runtime real com FakeAgent', async ({ page, request }, testInfo) => {
  test.setTimeout(90_000)
  const headers = { 'X-Maestro': '1' }
  const projects = await (await request.get('/api/projects', { headers })).json()
  const project = projects.find((p: { name: string }) => p.name === 'Trabalho Demo')
  expect(project).toBeTruthy()
  const title = 'Analisar contrato de pagamento pelo fluxo real'
  await page.goto('/inicio')
  await page.getByLabel('Projeto do objetivo').selectOption(String(project.id))
  await page.getByRole('textbox', { name: 'Objetivo para o CTO' }).fill(`E2E tarefa: ${title}`)
  await page.getByTestId('goal-submit').click()
  await expect(page).toHaveURL(new RegExp(`/cto\\?projeto=${project.id}$`))
  const coordinated = page.getByTestId('coordinator-work')
  await expect(coordinated.getByTestId('task-row')).toContainText(title)
  await expect(coordinated.getByTestId('agent-execution-detail')).toContainText('Investigação inicial do contrato')
  const decision = coordinated.getByTestId('work-decision')
  await expect(decision.getByRole('heading', { name: 'Manter o contrato atual nesta investigação?' })).toBeVisible()
  await decision.getByRole('button', { name: 'Manter contrato atual', exact: true }).click()
  await decision.getByRole('button', { name: 'Registrar decisão' }).click()
  await expect(coordinated.getByTestId('task-row')).toContainText('Concluída')
  await coordinated.getByTestId('task-row').click()
  await expect(page.getByRole('heading', { name: title, exact: true })).toBeVisible()
  const attempts = page.getByTestId('work-attempt')
  await expect(attempts).toHaveCount(3)
  await expect(page.getByRole('heading', { name: /Revisão #.*Aprovada/ })).toBeVisible()
  await attempts.nth(0).locator('summary').first().click()
  await expect(attempts.nth(0).getByTestId('attempt-result')).toContainText('Manter o contrato atual nesta investigação?')
  await expect(attempts.nth(0)).not.toContainText('Contrato atual preservado, investigação concluída.')
  await attempts.nth(1).locator('summary').first().click()
  await expect(attempts.nth(1).getByTestId('attempt-result')).toHaveText('Contrato atual preservado, investigação concluída.')
  await expect(attempts.nth(1).getByTestId('test-evidence')).toContainText('Não executado')
  await expect(page.getByText('Manter contrato atual', { exact: false }).first()).toBeVisible()

  const detail = await (await request.get(`/api/work-items/${page.url().split('/').at(-1)}`, { headers })).json()
  expect(detail.item.status).toBe('done')
  expect(new Set(detail.attempts.map((a: { session_id: string }) => a.session_id)).size).toBe(3)
  expect(detail.reviews[0].author_attempt_id).toBe(detail.attempts[1].id)
  expect(detail.reviews[0].review_attempt_id).toBe(detail.attempts[2].id)
  expect(detail.decisions[0].answer.answer).toBe('Manter contrato atual')

  for (const width of [1920, 1440, 1280, 1024, 768, 430, 375]) {
    await page.setViewportSize({ width, height: 900 })
    await expect(page.getByRole('heading', { name: title, exact: true })).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width + 1)
    if (width < 1024) {
      const toggle = page.getByRole('button', { name: 'Abrir navegação', exact: true })
      await toggle.focus(); await page.keyboard.press('Enter')
      await expect(page.getByRole('dialog', { name: 'Navegação' })).toBeVisible()
      await page.keyboard.press('Escape'); await expect(toggle).toBeFocused()
    }
    await page.screenshot({ path: testInfo.outputPath(`tarefa-real-${width}.png`), fullPage: true })
  }
  await page.goto('/sessions')
  for (const attempt of detail.attempts) await expect(page.locator(`a[href="/sessions/${attempt.session_id}"]`)).toHaveCount(0)
})
