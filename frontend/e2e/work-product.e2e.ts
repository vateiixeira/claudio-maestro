import { expect, test } from './fixtures'
import type { Page } from '@playwright/test'
const task = { id: 701, project_id: 1, title: 'Investigar falha no pagamento', source: 'sentry', external_id: 'LOJA-50', priority: 'high', status: 'waiting', phase: 'investigation', revision: 3, created_at: 100, updated_at: 200 }
async function mockWork(page: Page) {
  await page.route('**/api/work-items**', async route => {
    const url = new URL(route.request().url())
    const body = url.pathname === '/api/work-items/701'
      ? { item: task, dossier: { objective: 'Rastrear a falha no pagamento com evidências.', acceptance: 'Explicar a causa e demonstrar a correção.' }, attempts: [{ id: 71, work_item_id: 701, session_id: null, role: 'investigator', state: 'succeeded', work_revision: 3, created_at: 100, updated_at: 200, ended_at: 200, result: { summary: 'A investigação encontrou uma condição de corrida.', evidence: ['Reprodução isolada'], tests: ['Teste de regressão passou'], next_action: 'Decidir a publicação.' } }], events: [], dependencies: [], decisions: [], reviews: [] }
      : { items: !url.searchParams.get('status') || url.searchParams.get('status') === task.status ? [task] : [], total: 1, limit: Number(url.searchParams.get('limit') ?? 30), offset: Number(url.searchParams.get('offset') ?? 0) }
    await route.fulfill({ json: body })
  })
  await page.route('**/api/work/decisions?*', route => route.fulfill({ json: { items: [] } }))
  await page.route('**/api/work/notifications?*', route => route.fulfill({ json: { items: [], after: 0 } }))
  await page.route('**/api/work/sessions', route => route.fulfill({ json: {} }))
  await page.route('**/api/work/runtime', route => route.fulfill({ json: { dispatcher_enabled: false } }))
}
for (const width of [1920, 1440, 1280, 1024, 768, 430, 375]) {
  test(`início, tarefas e detalhe mantêm leitura e navegação em ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 }); await mockWork(page)
    await page.goto('/')
    await expect(page).toHaveURL(/\/inicio$/)
    await expect(page.getByRole('heading', { name: 'O que vamos resolver?' })).toBeVisible()
    await expect(page.getByTestId('goal-submit')).toBeDisabled()
    if (width < 1024) {
      const toggle = page.getByRole('button', { name: 'Abrir navegação', exact: true })
      await toggle.click(); await expect(page.getByRole('dialog', { name: 'Navegação' })).toBeVisible()
      await page.keyboard.press('Escape'); await expect(toggle).toBeFocused()
    }
    await page.goto('/tarefas?project=1&status=waiting&source=sentry')
    await expect(page.getByTestId('work-total')).toContainText('1 tarefa')
    await page.getByTestId('task-row').click()
    await expect(page.getByRole('heading', { name: task.title, exact: true })).toBeVisible()
    await expect(page.getByText('Decidir a publicação.', { exact: false }).first()).toBeVisible()
    await page.getByTestId('work-attempt').locator('summary').first().click()
    await expect(page.getByTestId('attempt-result')).toContainText('condição de corrida')
    const layout = await page.evaluate(() => ({ viewport: innerWidth, page: document.documentElement.scrollWidth }))
    expect(layout.page).toBeLessThanOrEqual(layout.viewport + 1)
  })
}

test('atividade recente mostra o evento 211 e permite percorrer todo o histórico anterior', async ({ page }) => {
  await mockWork(page)
  const events = Array.from({ length: 211 }, (_, i) => ({ id: i + 1, kind: 'item_updated', actor: `Execução ${i + 1}`, created_at: 100 + i, data: {} }))
  await page.route('**/api/work-items/701**', async route => {
    const url = new URL(route.request().url())
    const before = Number(url.searchParams.get('before')) || Infinity
    const items = events.filter(event => event.id < before).slice(-50)
    const cursor = items[0]!.id
    const metadata = { before: cursor, has_more: cursor > 1, limit: 50 }
    await route.fulfill({ json: url.pathname.endsWith('/events') ? { items, ...metadata } : { item: task, dossier: { objective: 'Conferir toda a atividade da tarefa.' }, attempts: [], dependencies: [], decisions: [], reviews: [], events: items, events_page: metadata } })
  })
  await page.goto('/tarefas/701')
  const activity = page.getByTestId('work-activity')
  await expect(activity).toContainText('Atividades recentes')
  await expect(activity.locator('[data-event-id="211"]')).toHaveCount(1)
  await expect(activity.locator('[data-event-id="1"]')).toHaveCount(0)
  for (let pageNumber = 0; pageNumber < 4; pageNumber++) await activity.getByRole('button', { name: 'Carregar atividades anteriores' }).click()
  await expect(activity.locator('[data-event-id="1"]')).toHaveCount(1)
  await expect(activity.locator('[data-event-id]')).toHaveCount(211)
  await expect(activity.locator('[data-event-id="211"]')).toHaveCount(1)
  await expect(activity.getByRole('button', { name: 'Carregar atividades anteriores' })).toHaveCount(0)
})
