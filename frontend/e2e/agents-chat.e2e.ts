import { expect, test } from './fixtures'

test('conversa com um agente, preserva a fila ao recarregar e retoma o mesmo contexto', async ({ page, baseURL }) => {
  const headers = { 'X-Maestro': '1', Origin: baseURL! }
  const name = `Conversa ${Date.now().toString(36)}`
  const project = (await (await page.request.get('/api/projects', { headers })).json())[0]
  const agent = await (await page.request.post('/api/specialists', { headers, data: { name, slug: `chat-${Date.now().toString(36)}`, project_id: project.id } })).json()
  try {
    await page.goto(`/agentes/${agent.id}`)
    await expect(page.getByTestId('agent-tab-conversations')).toHaveAttribute('aria-current', 'page')
    await page.getByTestId('queue-toggle').click()
    await expect(page.getByTestId('queue-state')).toHaveText('Fila pausada')
    await page.getByTestId('agent-chat-open').click()
    await expect(page).toHaveURL(/\/sessions\//)
    const chatUrl = page.url()
    await page.getByPlaceholder('Mensagem (Ctrl+V cola imagens)').fill('Pedido aguardando envio')
    await page.getByTestId('send').click()
    await expect(page.getByTestId('chat-queued-message')).toContainText('Pedido aguardando envio')
    await page.reload()
    await expect(page.getByTestId('agent-chat-queue')).toContainText('Fila pausada')
    await expect(page.getByTestId('chat-queued-message')).toContainText('Pedido aguardando envio')
    await page.getByTestId('chat-queue-cancel').click()
    await expect(page.getByTestId('chat-queued-message')).toHaveCount(0)
    await page.getByTestId('agent-chat-queue').getByRole('link', { name }).click()
    await page.getByTestId('queue-toggle').click()
    await page.getByTestId('agent-chat-open').click()
    await expect(page).toHaveURL(chatUrl)
    await page.getByPlaceholder('Mensagem (Ctrl+V cola imagens)').fill('Primeira pergunta do teste')
    await page.getByTestId('send').click()
    await expect(page.getByText('Resposta de teste: Primeira pergunta do teste', { exact: true })).toBeVisible()
    await page.getByPlaceholder('Mensagem (Ctrl+V cola imagens)').fill('Explique melhor a resposta')
    await page.getByTestId('send').click()
    await expect(page.getByText('Resposta de teste: Explique melhor a resposta', { exact: true })).toBeVisible()
    await expect(page).toHaveURL(chatUrl)
    await page.reload()
    await expect(page.getByText('Resposta de teste: Primeira pergunta do teste', { exact: true })).toBeVisible()
    await page.getByTestId('agent-chat-queue').getByRole('link', { name }).click()
    await page.getByTestId('agent-chat-new').click()
    await expect(page).not.toHaveURL(chatUrl)
    await expect(page.getByText('Resposta de teste: Primeira pergunta do teste', { exact: true })).toHaveCount(0)
    await page.screenshot({ path: '/tmp/maestro-agentes-conversa.png', fullPage: true })
  } finally {
    await page.goto('/agentes')
    await page.request.delete(`/api/specialists/${agent.id}`, { headers })
  }
})

test('continua o resultado de uma rotina na mesma conversa', async ({ page, baseURL }) => {
  const headers = { 'X-Maestro': '1', Origin: baseURL! }
  const project = (await (await page.request.get('/api/projects', { headers })).json())[0]
  const agent = await (await page.request.post('/api/specialists', { headers, data: { name: 'Continuar resultado', slug: `resultado-${Date.now().toString(36)}`, project_id: project.id } })).json()
  try {
    const run = await (await page.request.post(`/api/specialists/${agent.id}/run`, { headers, data: { text: 'Rotina do teste' } })).json()
    await page.goto(`/agentes/${agent.id}?aba=runs`)
    await page.getByTestId('run-continue').click()
    await expect(page).toHaveURL(new RegExp(`/sessions/${run.session_id}$`))
    await expect(page.getByText('Resposta de teste: Rotina do teste', { exact: true })).toBeVisible()
    await page.getByPlaceholder('Mensagem (Ctrl+V cola imagens)').fill('Por que fez isso?')
    await page.getByTestId('send').click()
    await expect(page.getByText('Resposta de teste: Por que fez isso?', { exact: true })).toBeVisible()
    await expect(page.getByText('Resposta de teste: Rotina do teste', { exact: true })).toBeVisible()
    const headerDoesNotOverlap = await page.evaluate(() => {
      const badge = document.querySelector('[data-test="agent-badge"]')!.getBoundingClientRect()
      const actions = document.querySelector('[data-test="header-actions"]')!.getBoundingClientRect()
      return badge.right <= actions.left || badge.bottom <= actions.top || actions.bottom <= badge.top
    })
    expect(headerDoesNotOverlap).toBe(true)
    await page.screenshot({ path: '/tmp/maestro-agentes-resultado.png', fullPage: true })
  } finally {
    await page.goto('/agentes')
    await page.request.delete(`/api/specialists/${agent.id}`, { headers })
  }
})
