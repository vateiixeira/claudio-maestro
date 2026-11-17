import { expect, test } from './fixtures'

test('a tela de entregas abre no dia de hoje, sem dia seguinte', async ({ page }) => {
  await page.goto('/entregas')

  await expect(page.getByTestId('prev-day')).toBeEnabled()
  await expect(page.getByTestId('next-day')).toBeDisabled()
})

// The seeded scenario has no deliveries, so the day is served by a stub (made-up records, no real data).
test.describe('com entregas no dia', () => {
  test.beforeEach(async ({ page, context }) => {
    await context.grantPermissions(['clipboard-read', 'clipboard-write'])
    const now = Math.floor(Date.now() / 1000)
    await page.route('**/api/deliveries?date=*', async (route) => {
      const date = new URL(route.request().url()).searchParams.get('date')
      await route.fulfill({
        json: {
          date,
          agent_enabled: false,
          prev_day: null,
          next_day: null,
          in_progress: [],
          deliveries: [
            { id: 9001, session_id: null, project_id: null, project_name: 'Alfa E2E', title: 'Primeira entrega da Alfa', finished_at: now - 300, status: 'done', summary_title: 'Primeira entrega da Alfa', bullets: ['Ajuste um'], error: null },
            { id: 9002, session_id: null, project_id: null, project_name: 'Beta E2E', title: 'Única entrega da Beta', finished_at: now - 200, status: 'done', summary_title: 'Única entrega da Beta', bullets: ['Ajuste dois'], error: null },
            { id: 9003, session_id: null, project_id: null, project_name: 'Alfa E2E', title: 'Segunda entrega da Alfa', finished_at: now - 100, status: 'done', summary_title: 'Segunda entrega da Alfa', bullets: ['Ajuste três'], error: null },
          ],
        },
      })
    })
  })

  test('escolher um projeto filtra a linha do tempo e escolher de novo volta a todos', async ({ page }) => {
    await page.goto('/entregas')
    const timeline = page.getByTestId('delivery-timeline')
    await expect(timeline.getByTestId('delivery')).toHaveCount(3)
    const chip = (project: string) => page.locator(`[data-test="delivery-filter"][data-project="${project}"]`)
    await expect(chip('')).toHaveAttribute('aria-pressed', 'true')

    await chip('Alfa E2E').click()
    await expect(chip('Alfa E2E')).toHaveAttribute('aria-pressed', 'true')
    await expect(timeline.getByTestId('delivery')).toHaveCount(2)
    await expect(timeline.getByText('Única entrega da Beta')).toHaveCount(0)

    await chip('Beta E2E').click()
    await expect(timeline.getByTestId('delivery')).toHaveCount(1)
    await expect(timeline.getByText('Única entrega da Beta')).toBeVisible()

    await chip('Beta E2E').click()
    await expect(timeline.getByTestId('delivery')).toHaveCount(3)
    await expect(chip('')).toHaveAttribute('aria-pressed', 'true')
  })

  test('Copiar esta entrega copia só aquela entrega e mostra o aviso', async ({ page }) => {
    await page.goto('/entregas')
    const second = page.getByTestId('delivery').filter({ hasText: 'Única entrega da Beta' })
    await second.getByRole('button', { name: 'Copiar esta entrega' }).click()
    await expect(second.getByTestId('copy-delivery')).toHaveAttribute('data-copied', 'true')
    await expect(page.getByTestId('copy-status')).toHaveText('Entrega copiada')
    const clipboard = await page.evaluate(() => navigator.clipboard.readText())
    expect(clipboard).toContain('Única entrega da Beta')
    expect(clipboard).not.toContain('Primeira entrega da Alfa')
    // The notice goes away by itself.
    await expect(page.getByTestId('copy-status')).toHaveText('')
  })
})
