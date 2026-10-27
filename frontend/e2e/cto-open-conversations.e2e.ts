import { expect, test } from './fixtures'

test('o CTO da barra lateral lista as conversas em andamento e só cria a conversa ao escolher o projeto', async ({ page }) => {
  const created: string[] = []
  page.on('request', (request) => {
    if (request.method() === 'POST' && /\/api\/projects\/\d+\/cto$/.test(request.url())) created.push(request.url())
  })
  await page.goto('/projects/1')
  await page.getByTestId('nav-cto').click()
  await expect(page).toHaveURL(/\/cto$/)
  await expect(page.getByRole('heading', { name: 'Um CTO por projeto' })).toBeVisible()
  expect(created).toEqual([])

  // Open the CTO of one project (the scenario has no previous conversation for it).
  await page.getByTestId('cto-item').filter({ hasText: 'Ramos Demo' }).click()
  await expect(page).toHaveURL(/\/cto\?projeto=\d+$/)
  await expect.poll(() => created.length).toBeGreaterThan(0)
  const opened = page.url()

  // Back through the sidebar: always the list, now with that conversation first.
  await page.getByTestId('nav-cto').click()
  await expect(page).toHaveURL(/\/cto$/)
  const open = page.getByTestId('cto-open')
  await expect(open.getByRole('heading', { name: 'Conversas em andamento' })).toBeVisible()
  const ramos = open.getByTestId('cto-item').filter({ hasText: 'Ramos Demo' })
  await expect(ramos).toHaveCount(1)
  await expect(page.getByTestId('cto-others').getByTestId('cto-item').filter({ hasText: 'Ramos Demo' })).toHaveCount(0)
  await expect(page.getByTestId('cto-others').getByRole('heading', { name: 'Outros projetos' })).toBeVisible()
  await expect(page.getByLabel('Projeto do CTO').getByRole('option', { name: 'Ramos Demo · em andamento' })).toHaveCount(1)
  const before = created.length

  // Listing again creates nothing; clicking the entry goes to the same project.
  await ramos.click()
  await expect(page).toHaveURL(opened)

  // Narrow screen: the list fits without horizontal scroll.
  await page.setViewportSize({ width: 400, height: 800 })
  await page.getByRole('button', { name: 'Abrir navegação' }).first().click()
  await page.getByRole('dialog', { name: 'Navegação' }).getByTestId('nav-cto').click()
  await expect(page).toHaveURL(/\/cto$/)
  await expect(page.getByTestId('cto-open').getByTestId('cto-item').first()).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(401)
  expect(created.length).toBe(before + 1) // only the click on the entry opened a conversation; the sidebar lists never did
})
