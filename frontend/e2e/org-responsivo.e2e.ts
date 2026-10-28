import { expect, test } from './fixtures'
import { expectNoHorizontalScroll, openOrganization, taskRow } from './org-helpers'

// The Organização, a task and the Início keep their controls usable, with no horizontal scroll,
// from a wide screen down to a phone.

for (const width of [1920, 1440, 1280, 1024, 768, 430, 375]) {
  test(`a Organização, o painel do agente e a tarefa cabem em ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await openOrganization(page)
    await expect(page.getByTestId('org-tree')).toBeVisible()
    await expect(page.getByTestId('org-node-button').filter({ hasText: 'Triagem' })).toBeVisible()
    for (const tab of ['tarefas', 'rotinas', 'execucoes']) {
      await page.getByTestId(`org-tab-${tab}`).click()
      await expect(page.getByTestId(`org-tab-${tab}`)).toHaveAttribute('aria-selected', 'true')
      await expectNoHorizontalScroll(page)
    }

    await page.getByTestId('org-node-button').filter({ hasText: 'Triagem' }).click()
    await expect(page.getByTestId('agent-panel').getByRole('heading', { level: 2, name: 'Triagem' })).toBeVisible()
    for (const tab of ['conversa', 'definicao', 'execucoes']) {
      await page.getByTestId(`agent-tab-${tab}`).click()
      await expect(page.getByTestId(`agent-tab-${tab}`)).toHaveAttribute('aria-selected', 'true')
      await expectNoHorizontalScroll(page)
    }
    expect((await page.getByTestId('agent-panel').boundingBox())!.width).toBeGreaterThan(250)

    await page.getByTestId('org-back').click()
    await taskRow(page, 'Separar chamados urgentes').click()
    await expect(page.getByRole('heading', { level: 1 })).toContainText('Separar chamados urgentes')
    await expect(page.getByTestId('task-composer-submit')).toBeVisible()
    await expectNoHorizontalScroll(page)

    await page.goto('/inicio')
    await expect(page.getByRole('heading', { level: 1, name: 'O que vamos resolver?' })).toBeVisible()
    await expectNoHorizontalScroll(page)

    if (width < 1024) {
      await page.goto('/agentes')
      const toggle = page.getByTestId('agents-mobile-menu')
      await expect(toggle).toBeVisible()
      await toggle.click()
      await expect(page.getByRole('dialog', { name: 'Navegação' })).toBeVisible()
      await page.keyboard.press('Escape')
      await expect(page.getByRole('dialog', { name: 'Navegação' })).toHaveCount(0)
    }
  })
}
