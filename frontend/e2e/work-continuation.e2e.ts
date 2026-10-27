import { expect, test } from './fixtures'

test('orientação retoma a coleta exata, libera a fila e distingue avisos de fala humana', async ({ page, request, consoleErrors }, testInfo) => {
  test.setTimeout(90_000)
  const headers = { 'X-Maestro': '1' }
  const read = async (path: string) => (await request.get(path, { headers })).json()
  const project = (await read('/api/projects')).find((p: { name: string }) => p.name === 'Coleta Demo')
  expect(project).toBeTruthy()
  await page.goto('/inicio')
  await page.getByLabel('Projeto do objetivo').selectOption(String(project.id))
  await page.getByRole('textbox', { name: 'Objetivo para o CTO' }).fill('E2E coleta: Investigar filtros disponíveis')
  await page.getByTestId('goal-submit').click()
  await expect(page).toHaveURL(new RegExp(`/cto\\?projeto=${project.id}$`))
  const ctoUrl = page.url()
  const summary = page.getByTestId('coordinator-next-step')
  await expect(summary).toContainText('Parou sem registrar uma entrega')
  await expect(summary).toContainText(/Na fila, aguardando .*sentry/i)
  const overview = await read(`/api/projects/${project.id}/work-overview`)
  const sentry = overview.items.find((item: { kind: string }) => item.kind === 'continuation')
  const queued = overview.items.find((item: { kind: string }) => item.kind === 'queued')
  expect(queued.queue_reason.work_item_id).toBe(sentry.work_item_id)
  const original = await read(`/api/work-items/${sentry.work_item_id}`)
  expect(original.attempts).toHaveLength(1)
  expect(original.attempts[0].state).toBe('waiting')
  expect(original.attempts[0].result).toBeNull()
  expect(original.decisions).toHaveLength(0)
  expect((await read(`/api/work-items/${queued.work_item_id}`)).attempts).toHaveLength(0)
  const destination = `/tarefas/${sentry.work_item_id}#attempt-${sentry.attempt_id}`
  const action = summary.getByTestId('continue-work')
  await expect(action).toHaveAttribute('href', destination)

  for (const width of [1440, 1280, 375]) {
    await page.setViewportSize({ width, height: width === 1440 ? 900 : 720 })
    await page.getByTestId('conversation-scroller').evaluate(element => { element.scrollTop = element.scrollHeight })
    await expect(summary).toBeInViewport()
    expect(await page.getByTestId('conversation-scroller').evaluate(element => element.clientHeight), 'A conversa precisa manter espaço legível ao lado do resumo e do compositor').toBeGreaterThanOrEqual(160)
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width + 1)
    await page.screenshot({ path: testInfo.outputPath(`coleta-resumo-${width}.png`), fullPage: true })
    if (width === 375 || width === 1280) {
      const moreSteps = page.getByTestId('attention-details-toggle')
      await moreSteps.focus()
      await page.keyboard.press('Enter')
      await expect(moreSteps).toHaveAttribute('aria-expanded', 'true')
      await expect(summary.getByText(/Na fila, aguardando .*sentry/i)).toBeVisible()
      await page.screenshot({ path: testInfo.outputPath(`coleta-resumo-expandido-${width}.png`), fullPage: true })
      await moreSteps.focus()
      await page.keyboard.press('Enter')
      await expect(moreSteps).toHaveAttribute('aria-expanded', 'false')
      for (const id of [...(width === 375 ? ['cto-project-options-toggle'] : []), 'mobile-header-actions', 'composer-options-toggle']) {
        const toggle = page.getByTestId(id)
        await expect(toggle).toHaveAttribute('aria-expanded', 'false')
        await toggle.focus()
        await page.keyboard.press('Enter')
        await expect(toggle).toHaveAttribute('aria-expanded', 'true')
        const panelId = await toggle.getAttribute('aria-controls')
        await expect(page.locator(`[id="${panelId}"]`)).toBeVisible()
        if (id === 'mobile-header-actions') {
          await page.getByRole('button', { name: 'Mais ações', exact: true }).click()
          await expect(page.getByRole('menuitem', { name: 'Copiar ID da sessão' })).toBeInViewport()
          await page.keyboard.press('Escape')
          await expect(page.getByRole('menu')).toHaveCount(0)
        } else if (id === 'composer-options-toggle') {
          for (const name of [/^Modelo:/, /^Permissões:/]) {
            await page.getByRole('button', { name }).click()
            const menu = page.getByRole('menu', { name })
            await expect(menu).toBeInViewport()
            await expect(menu.getByRole('menuitemradio').first()).toBeInViewport()
            await page.keyboard.press('Escape')
            await expect(menu).toHaveCount(0)
          }
        }
        await toggle.focus()
        await page.keyboard.press('Enter')
        await expect(toggle).toHaveAttribute('aria-expanded', 'false')
      }
    }
  }
  await action.focus()
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(new RegExp(`${destination}$`))
  const attempt = page.getByTestId('work-attempt').filter({ has: page.locator(`#orientation-${sentry.attempt_id}`) })
  await expect(attempt).toHaveAttribute('data-attempt-id', String(sentry.attempt_id))
  await expect(attempt.getByTestId('agent-execution-detail')).toContainText('Qual filtro devo usar para continuar?')
  const orientation = page.getByLabel(`Orientação para ${sentry.title}, tentativa #${sentry.attempt_id}`, { exact: true })
  await expect(orientation).toHaveValue('')
  const draft = 'Use environment:prd, o alias informado pela fonte, e publique os metadados da coleta.'
  await orientation.fill(draft)
  await page.screenshot({ path: testInfo.outputPath('coleta-orientacao-375.png'), fullPage: true })
  const endpoint = `**/api/sessions/${sentry.session_id}/messages`
  // These controlled responses exercise only the error UI. The successful send below reaches the real fake-backed runtime.
  for (const status of [409, 202]) {
    let calls = 0
    await page.route(endpoint, async route => {
      calls++
      await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(status === 409 ? { detail: 'Execução ocupada no teste de conflito' } : { state: 'error', send_started: false }) })
    })
    await page.getByRole('button', { name: 'Enviar orientação', exact: true }).click()
    await expect(page.getByRole('alert')).toContainText('O rascunho foi mantido')
    await expect(orientation).toHaveValue(draft)
    await expect(page.getByRole('button', { name: 'Enviar orientação', exact: true })).toBeEnabled()
    expect(calls).toBe(1)
    await page.unroute(endpoint)
    if (status === 409) {
      const index = consoleErrors.findIndex(text => /Failed to load resource.*409/.test(text))
      if (index !== -1) consoleErrors.splice(index, 1)
    }
  }
  await page.reload()
  await expect(orientation).toHaveValue(draft)
  await page.getByRole('button', { name: 'Enviar orientação', exact: true }).focus()
  await page.keyboard.press('Enter')
  await expect.poll(async () => (await read(`/api/work-items/${sentry.work_item_id}`)).item.status).toBe('done')
  await expect.poll(async () => (await read(`/api/work-items/${queued.work_item_id}`)).item.status).toBe('done')
  const finished = await read(`/api/work-items/${sentry.work_item_id}`)
  expect(finished.attempts).toHaveLength(1)
  expect(finished.attempts[0].id).toBe(sentry.attempt_id)
  expect(finished.attempts[0].session_id).toBe(sentry.session_id)
  expect((await read(`/api/work-items/${queued.work_item_id}`)).attempts).toHaveLength(1)
  const collections = await read(`/api/projects/${project.id}/collections`)
  expect(collections.items).toHaveLength(2)
  expect(collections.items.every((item: { status: string }) => item.status === 'done')).toBe(true)
  await page.goto(ctoUrl)
  await expect(summary).toContainText('Nenhuma ação pendente para você')
  const automatic = page.getByTestId('automatic-message')
  await expect(automatic.first()).toBeAttached()
  for (const message of await automatic.all()) {
    await expect(message).not.toHaveAttribute('open')
    await expect(message.locator('summary')).toHaveText('Atualização automática')
  }
  await automatic.last().locator('summary').click()
  await expect(automatic.last().locator('pre')).toContainText('Avisos automáticos do Maestro.')
  await automatic.last().locator('summary').click()
  const human = 'Avisos automáticos do Maestro. Esta é uma mensagem humana de conferência, sem autorização adicional.'
  await page.getByPlaceholder('Mensagem (Ctrl+V cola imagens)').fill(human)
  await page.getByTestId('send').click()
  await expect(page.getByTestId('user-message').filter({ hasText: human })).toBeVisible()
  await expect(page.getByTestId('turn-bar')).not.toContainText('notification_id')
  await page.reload()
  await expect(page.getByTestId('user-message').filter({ hasText: human })).toBeVisible()
  await expect(automatic.first()).not.toHaveAttribute('open')
  for (const width of [1440, 1280, 375]) {
    await page.setViewportSize({ width, height: width === 1440 ? 900 : 720 })
    await expect(summary).toBeInViewport()
    expect(await page.getByTestId('conversation-scroller').evaluate(element => element.clientHeight), 'A conversa precisa manter espaço legível ao lado do resumo e do compositor').toBeGreaterThanOrEqual(160)
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width + 1)
    if (width >= 1280) {
      await expect(page.getByTestId('details-properties')).toContainText('CTO disponível')
      await expect(page.getByTestId('details-properties')).not.toContainText('Sua vez')
    }
    await page.screenshot({ path: testInfo.outputPath(`coleta-concluida-${width}.png`), fullPage: true })
  }
})
