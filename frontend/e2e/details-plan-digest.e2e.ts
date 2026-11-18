import type { Page } from '@playwright/test'
import { expect, openSeededSession, test } from './fixtures'

// The seeded conversations have no plan and no summary, so the snapshot of one of them is completed
// with a plan, and the answers of /plan, /plans and /digest are staged by the spec.
const PLAN_PATH = '/tmp/loja-demo/docs/superpowers/plans/2026-11-17-carrinho.md'
const PLAN = { path: PLAN_PATH, title: 'Carrinho de compras', total: 6, done: 2, current: { number: 3, title: 'Calcular o frete' } }
const TASKS = [
  { number: 1, title: 'Criar o carrinho', done: true },
  { number: 2, title: 'Somar os itens', done: true },
  { number: 3, title: 'Calcular o frete', done: false },
  { number: 4, title: 'Aplicar o cupom', done: false },
  { number: 5, title: 'Fechar o pedido', done: false },
  { number: 6, title: 'Enviar o recibo', done: false },
]
const READ_AT = Math.floor(Date.now() / 1000) - 120
const DIGEST = {
  session_id: 'x',
  read_at: READ_AT,
  short: 'O carrinho soma os itens e falta calcular o frete.',
  plan_done: false,
  error: null,
  error_at: null,
  phases: [
    {
      title: 'Plano do carrinho', kind: 'plan', status: 'done', ref: 'docs/superpowers/plans/2026-11-17-carrinho.md',
      done: ['Escreveu o plano em seis tarefas', 'Revisou o plano com o mantenedor'], pending: [],
    },
    {
      title: 'Implementar o frete', kind: 'feature', status: 'open', ref: null,
      done: ['Criou a função do frete'], pending: ['Escrever o teste do frete'],
    },
  ],
}

async function stagePlan(page: Page) {
  // Opening a conversation marks it as seen, and the server answers with a `session.updated` without the
  // staged plan; the reading receipt is not what these specs are about.
  await page.route(/\/api\/sessions\/[0-9a-f-]+\/seen$/, (route) => (route.request().method() === 'POST' ? route.fulfill({ json: {} }) : route.fallback()))
  const withPlan = (session: Record<string, unknown>) => ({ ...session, plan: PLAN })
  await page.route(/\/api\/projects\/\d+\/sessions$/, async (route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    const response = await route.fetch()
    const list = await response.json() as Record<string, unknown>[]
    await route.fulfill({ response, json: list.map((s) => (s.title === 'Explique a estrutura do projeto' ? withPlan(s) : s)) })
  })
  await page.route(/\/api\/sessions\/[0-9a-f-]+$/, async (route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    const response = await route.fetch()
    const snapshot = await response.json()
    await route.fulfill({ response, json: withPlan(snapshot) })
  })
  const calls: string[] = []
  let state: Record<string, unknown> = { link: 'auto', path: PLAN_PATH, plan: PLAN, tasks: TASKS }
  await page.route(/\/api\/sessions\/[0-9a-f-]+\/plan$/, async (route) => {
    const request = route.request()
    if (request.method() === 'DELETE') {
      calls.push('DELETE')
      state = { link: 'off', path: null, plan: null, tasks: [] }
    } else if (request.method() === 'PUT') {
      calls.push(`PUT ${request.postData()}`)
      state = { link: 'auto', path: PLAN_PATH, plan: PLAN, tasks: TASKS }
    }
    await route.fulfill({ json: state })
  })
  await page.route(/\/api\/projects\/\d+\/plans$/, (route) => route.fulfill({
    json: [{ path: PLAN_PATH, title: 'Carrinho de compras', total: 6, done: 2 }, { path: '/tmp/loja-demo/docs/superpowers/plans/outro.md', title: 'Outro plano', total: 3, done: 0 }],
  }))
  await page.route(/\/api\/sessions\/[0-9a-f-]+\/digest$/, (route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    return route.fulfill({ json: DIGEST })
  })
  return calls
}

async function openDetails(page: Page) {
  await openSeededSession(page)
  // The conversation is on screen (the panel's own state is settled) before deciding whether to open it.
  await expect(page.getByTestId('turn-number').first()).toBeVisible()
  if (!(await page.getByTestId('details-panel').isVisible())) await page.getByTestId('toggle-details').first().click()
  await expect(page.getByTestId('details-plan')).toBeVisible()
}

test('o painel Detalhes abre com Plano e Resumo no topo, antes das Propriedades', async ({ page }) => {
  await stagePlan(page)
  await openDetails(page)
  const order = await page.evaluate(() => ['details-plan', 'details-digest', 'details-properties']
    .map((name) => document.querySelector(`[data-test="${name}"]`)!.getBoundingClientRect().y))
  expect(order[0]).toBeLessThan(order[1]!)
  expect(order[1]).toBeLessThan(order[2]!)
  await expect(page.getByTestId('details-digest').getByRole('heading', { name: /Resumo/ })).toBeVisible()
  // The plan toggle of the strip above the composer is not in the panel.
  await expect(page.getByTestId('details-plan').getByTestId('plan-toggle')).toHaveCount(0)
})

test('o plano mostra o nome, a posição, uma barra em segmentos e as tarefas', async ({ page }) => {
  await stagePlan(page)
  await openDetails(page)
  const plan = page.getByTestId('details-plan')
  await expect(plan.getByTestId('plan-name')).toHaveText('Carrinho de compras')
  // Nothing runs the seeded conversation, so it says so.
  await expect(plan.getByTestId('plan-position')).toHaveText('3 de 6 · parado')
  const segments = plan.getByTestId('plan-segment')
  await expect(segments).toHaveCount(6)
  expect(await segments.evaluateAll((els) => els.map((el) => el.getAttribute('data-status')))).toEqual(['done', 'done', 'current', 'queued', 'queued', 'queued'])
  await expect(plan.getByTestId('plan-progress')).toHaveAccessibleName('Progresso do plano')
  await expect(plan.getByTestId('plan-progress')).toHaveAttribute('aria-valuetext', '2 concluídas, 1 em andamento, 3 pendentes')

  // The current task, the next two and "+1 depois"; the two done ones stay in view (three or fewer).
  const tasks = plan.getByTestId('plan-task')
  await expect(tasks.filter({ hasText: 'Calcular o frete' })).toContainText('Agora')
  await expect(plan.getByText('Criar o carrinho')).toBeVisible()
  await expect(plan.getByText('Aplicar o cupom')).toBeVisible()
  await expect(plan.getByText('Fechar o pedido')).toBeVisible()
  await expect(plan.getByText('Enviar o recibo')).toHaveCount(0)
  await expect(plan.getByTestId('plan-later')).toHaveText('+1 depois')
  await expect(plan.getByTestId('plan-open')).toBeVisible()
})

test('o menu "⋯" do plano troca, desliga e volta a ligar automaticamente', async ({ page }) => {
  const calls = await stagePlan(page)
  await openDetails(page)
  const plan = page.getByTestId('details-plan')
  const more = plan.getByTestId('plan-more')
  await expect(more).toHaveAccessibleName('Mais ações do plano: trocar ou desligar')
  await more.click()
  const items = page.getByTestId('more-menu-item')
  await expect(items).toHaveText(['Trocar plano…', 'Desligar'])

  // "Trocar plano…" lists the plans of the project, the linked one marked.
  await items.first().click()
  const choices = page.getByRole('menu', { name: 'Planos do projeto' })
  await expect(choices.getByRole('menuitem')).toHaveCount(2)
  await expect(choices.getByRole('menuitem', { name: /Carrinho de compras/ })).toContainText('2/6')
  await page.keyboard.press('Escape')
  await expect(choices).toHaveCount(0)

  // "Desligar" stops following; the menu then offers to turn it on again.
  await more.click()
  await page.getByRole('menuitem', { name: 'Desligar' }).click()
  await expect.poll(() => calls).toEqual(['DELETE'])
  await more.click()
  await expect(page.getByTestId('more-menu-item')).toHaveText(['Escolher plano…', 'Ligar automaticamente'])
  await page.getByRole('menuitem', { name: 'Ligar automaticamente' }).click()
  await expect.poll(() => calls).toEqual(['DELETE', 'PUT {"auto":true}'])
})

test('o resumo mostra o texto curto, a hora da leitura e as fases como linha do tempo', async ({ page }) => {
  await stagePlan(page)
  await openDetails(page)
  const digest = page.getByTestId('details-digest')
  await expect(digest.getByTestId('digest-short')).toHaveText('O carrinho soma os itens e falta calcular o frete.')
  await expect(digest.getByTestId('digest-read-at')).toHaveText(/^atualizado há 2 min$/)
  const phases = digest.getByTestId('digest-phase')
  await expect(phases).toHaveCount(2)
  await expect(phases.nth(0).getByTestId('digest-phase-node')).toHaveAttribute('data-status', 'done')
  await expect(phases.nth(1).getByTestId('digest-phase-node')).toHaveAttribute('data-status', 'open')
  await expect(phases.nth(0)).toContainText('2026-11-17-carrinho.md')
  // What is missing is in view; the steps already done are folded.
  await expect(phases.nth(1)).toContainText('Falta')
  await expect(phases.nth(1)).toContainText('Escrever o teste do frete')
  await expect(digest.getByTestId('digest-done-item')).toHaveCount(0)
  await expect(digest.getByTestId('digest-request')).toHaveText('Resumir agora')
})

test('"Ver os N passos" abre e recolhe os passos feitos de uma fase', async ({ page }) => {
  await stagePlan(page)
  await openDetails(page)
  const phases = page.getByTestId('details-digest').getByTestId('digest-phase')
  const first = phases.nth(0).getByTestId('digest-steps-toggle')
  await expect(first).toHaveText('Ver os 2 passos')
  await expect(first).toHaveAttribute('aria-expanded', 'false')
  await first.click()
  await expect(first).toHaveText('2 passos')
  await expect(first).toHaveAttribute('aria-expanded', 'true')
  await expect(phases.nth(0).getByTestId('digest-done-item')).toHaveText(['Escreveu o plano em seis tarefas', 'Revisou o plano com o mantenedor'])
  // Another phase is not touched, and a single step reads in the singular.
  await expect(phases.nth(1).getByTestId('digest-done-item')).toHaveCount(0)
  await expect(phases.nth(1).getByTestId('digest-steps-toggle')).toHaveText('Ver 1 passo')

  await first.focus()
  await page.keyboard.press('Enter')
  await expect(first).toHaveAttribute('aria-expanded', 'false')
  await expect(phases.nth(0).getByTestId('digest-done-item')).toHaveCount(0)
})

test('o menu "⋯" do plano abre pelo teclado, anda com as setas e devolve o foco ao fechar', async ({ page }) => {
  await stagePlan(page)
  await openDetails(page)
  const more = page.getByTestId('details-plan').getByTestId('plan-more')
  await more.focus()
  await page.keyboard.press('Enter')
  const items = page.getByRole('menuitem')
  await expect(items.first()).toBeFocused()
  await page.keyboard.press('ArrowDown')
  await expect(items.nth(1)).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(items).toHaveCount(0)
  await expect(more).toBeFocused()
  expect(await more.evaluate((el) => getComputedStyle(el).outlineStyle)).not.toBe('none')
})
