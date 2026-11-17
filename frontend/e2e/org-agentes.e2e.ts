import { expect, test } from './fixtures'
import { expectNoHorizontalScroll } from './org-helpers'

// /agentes always opens the overview of the projects, even after visiting one of them.

test('/agentes mostra a visão geral: o projeto com organização em cartão e os outros com "Criar"', async ({ page }) => {
  await page.goto('/agentes')
  const overview = page.getByTestId('org-overview')
  await expect(overview).toBeVisible()
  const card = overview.getByTestId('org-overview-project').filter({ hasText: 'Loja Demo' })
  await expect(card).toBeVisible()
  await expect(card.getByTestId('org-overview-meta')).toHaveText('3 agentes')
  await expect(card.getByTestId('org-overview-agent')).toHaveCount(3)
  for (const name of ['Maestro', 'Revisor', 'Triagem']) {
    await expect(card.getByTestId('org-overview-agent').filter({ hasText: name })).toBeVisible()
  }
  // Triagem has the unread notice and a routine; the other two have neither.
  const triagem = card.getByTestId('org-overview-agent').filter({ hasText: 'Triagem' })
  await expect(triagem.getByTestId('org-overview-next')).toHaveText(/\d{2}:\d{2}/)
  await expect(card.getByTestId('org-overview-agent').filter({ hasText: 'Revisor' }).getByTestId('org-overview-next')).toHaveText('sob demanda')

  const without = overview.getByTestId('org-overview-without')
  const painel = without.getByTestId('org-project-option').filter({ hasText: 'Painel Demo' })
  await expect(painel).toContainText('Criar')
  await expect(without.getByTestId('org-project-option').filter({ hasText: 'Loja Demo' })).toHaveCount(0)
})

test('abrir o cartão leva à organização, e voltar a /agentes mostra a visão geral de novo', async ({ page }) => {
  await page.goto('/agentes')
  await page.getByTestId('org-overview-project').filter({ hasText: 'Loja Demo' }).getByTestId('org-project-option').click()
  await expect(page).toHaveURL(/\/agentes\/\d+/)
  await expect(page.getByRole('heading', { level: 1, name: 'Loja Demo' })).toBeVisible()
  await expect(page.getByTestId('org-tree')).toBeVisible()

  // The link of the navigation does not jump to the project visited last.
  await page.getByRole('navigation', { name: 'Navegação' }).getByTestId('nav-agents').click()
  await expect(page).toHaveURL(/\/agentes$/)
  await expect(page.getByTestId('org-overview')).toBeVisible()
  await expect(page.getByTestId('org-tree')).toHaveCount(0)
})

test('uma linha de agente do cartão abre o painel dele', async ({ page }) => {
  await page.goto('/agentes')
  await page.getByTestId('org-overview-agent').filter({ hasText: 'Revisor' }).click()
  await expect(page).toHaveURL(/agente=\d+/)
  await expect(page.getByTestId('agent-panel').getByRole('heading', { level: 2, name: 'Revisor' })).toBeVisible()
})

test('um projeto sem organização abre a página dele, pronta para criar o primeiro agente', async ({ page }) => {
  await page.goto('/agentes')
  await page.getByTestId('org-overview-without').getByTestId('org-project-option').filter({ hasText: 'Painel Demo' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Painel Demo' })).toBeVisible()
  await expect(page.getByTestId('org-tree-empty')).toBeVisible()
  await expect(page.getByTestId('new-agent')).toBeVisible()
})

for (const width of [1280, 768, 430, 375]) {
  test(`a visão geral cabe em ${width}px e o nome do agente não some sob outra coluna`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await page.goto('/agentes')
    const card = page.getByTestId('org-overview-project').filter({ hasText: 'Loja Demo' })
    await expect(card).toBeVisible()
    await expectNoHorizontalScroll(page)
    for (const name of ['Maestro', 'Revisor', 'Triagem']) {
      const line = card.getByTestId('org-overview-agent').filter({ hasText: name })
      await expect(line).toBeVisible()
      const label = (await line.getByText(name, { exact: true }).first().boundingBox())!
      const unseen = (await line.getByTestId('org-overview-agent-unseen').boundingBox())!
      expect(label.x + label.width, `"${name}" termina antes da coluna de novidades`).toBeLessThanOrEqual(unseen.x + 1)
    }
  })
}
