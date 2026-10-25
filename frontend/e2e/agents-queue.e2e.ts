import { expect, test } from './fixtures'

test('pausa a fila, preserva a execução ao recarregar e cancela antes de começar', async ({ page, baseURL }) => {
  const name = `Fila ${Date.now().toString(36)}`
  let agentId: string | undefined
  const headers = { 'X-Maestro': '1', Origin: baseURL! }
  try {
    await page.goto('/agentes')
    await page.getByTestId('agent-new').click()
    await page.getByTestId('new-name').fill(name)
    await page.getByRole('dialog').getByRole('button', { name: 'Criar' }).click()
    await expect(page.getByTestId('agent-name')).toHaveText(name)
    agentId = /\/agentes\/(\d+)/.exec(page.url())![1]

    await page.getByRole('button', { name: 'Pausar fila', exact: true }).click()
    await expect(page.getByTestId('queue-state')).toHaveText('Fila pausada')
    await expect(page.getByTestId('agent-enabled')).toHaveAttribute('aria-checked', 'true')

    await page.getByTestId('run-now').click()
    await page.getByTestId('run-text').fill('Somente uma execução de teste, aguardando na fila.')
    await page.getByRole('dialog').getByRole('button', { name: 'Rodar', exact: true }).click()
    await expect(page).toHaveURL(new RegExp(`/agentes/${agentId}(?:\\?.*)?$`))
    await expect(page.getByTestId('action-status')).toHaveText('Execução adicionada à fila.')
    await expect(page.getByTestId('run-row')).toContainText('Na fila')
    await expect(page.getByTestId('run-row').getByRole('link', { name: 'Abrir' })).toHaveCount(0)

    await page.reload()
    await expect(page.getByTestId('queue-state')).toHaveText('Fila pausada')
    await expect(page.getByTestId('run-row')).toContainText('Na fila')
    await page.getByTestId('run-row').getByRole('button', { name: 'Cancelar', exact: true }).click()
    await expect(page.getByTestId('run-row')).toContainText('Cancelada')
    await expect(page.getByTestId('run-cancel')).toHaveCount(0)

    await page.getByRole('button', { name: 'Retomar fila', exact: true }).click()
    await expect(page.getByTestId('queue-state')).toHaveText('Fila ativa')
    await page.reload()
    await expect(page.getByTestId('queue-state')).toHaveText('Fila ativa')
    await expect(page.getByTestId('run-row')).toContainText('Cancelada')
    await expect(page.getByTestId('run-row').getByRole('link', { name: 'Abrir' })).toHaveCount(0)
  } finally {
    if (agentId) {
      // Leave the detail before deleting its agent, so its live file refreshes do not race cleanup.
      await page.goto('/agentes')
      const response = await page.request.delete(`/api/specialists/${agentId}`, { headers })
      expect(response.status()).toBe(204)
    }
  }
})
