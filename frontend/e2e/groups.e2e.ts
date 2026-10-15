import type { Page } from '@playwright/test'
import { expect, test } from './fixtures'

// The texts below are the SCENARIO of scripts/e2e_server.py: a group made in "Loja Demo" (A)
// holds one conversation of A and one of "Painel Demo" (B). Groups are global and the database
// lives through the whole run, so every test deletes the groups it made (afterEach); deleting a
// group releases its conversations.
const A = 'Loja Demo'
const B = 'Painel Demo'
const A_TITLE = 'Explique a estrutura do projeto'
const B_TITLE = 'Resuma o último commit'
const GROUP = 'Pagamento'

test.afterEach(async ({ page, baseURL }) => {
  const headers = { 'X-Maestro': '1', Origin: baseURL! }
  const list = await page.request.get('/api/groups', { headers })
  for (const group of (await list.json()) as { id: number }[]) {
    await page.request.delete(`/api/groups/${group.id}`, { headers })
  }
})

const sidebar = (page: Page) => page.getByRole('navigation', { name: 'Navegação' })

async function openProject(page: Page, name: string) {
  await sidebar(page).getByTestId('project').filter({ hasText: name }).click()
  await expect(page.getByRole('heading', { name, level: 1 })).toBeVisible()
}

async function openConversation(page: Page, title: string) {
  await page.goto('/sessions')
  await page.getByTestId('row-link').filter({ hasText: title }).first().click()
  await expect(page).toHaveURL(/\/sessions\/[0-9a-f-]+/)
  const group = page.getByTestId('prop-group')
  if (!(await group.isVisible())) await page.getByTestId('toggle-details').first().click()
  await expect(group).toBeVisible()
  return group
}

/** Creates GROUP on the screen of A, puts one conversation of B and one of A in it. */
async function seedGroup(page: Page) {
  await page.goto('/inbox')
  await openProject(page, A)
  await page.getByTestId('group-new').click()
  await page.getByTestId('group-new-name').fill(GROUP)
  await page.getByTestId('group-new-name').press('Enter')
  await expect(page.getByTestId('group-section').filter({ hasText: GROUP })).toBeVisible()
  // The group is empty, yet the screen of its project shows it.
  await expect(page.getByTestId('group-count')).toHaveText('Nenhuma conversa')

  // B's conversation picks the group of another project: "Nome · Projeto".
  const fromB = await openConversation(page, B_TITLE)
  await expect(fromB.getByRole('option', { name: `${GROUP} · ${A}` })).toHaveCount(1)
  await fromB.selectOption({ label: `${GROUP} · ${A}` })
  await expect(fromB).toHaveValue(/\d+/)

  const fromA = await openConversation(page, A_TITLE)
  await fromA.selectOption({ label: GROUP })
  await expect(fromA).toHaveValue(/\d+/)
}

test('agrupador criado em um projeto aparece nas telas e na barra lateral dos dois', async ({ page }) => {
  await seedGroup(page)

  // Sidebar: under each project, with the conversations of both; the foreign one names its project.
  const groups = sidebar(page).getByTestId('sidebar-group')
  await expect(groups).toHaveCount(2)
  for (const group of await groups.all()) {
    await expect(group.getByTestId('sidebar-session')).toHaveCount(2)
    await expect(group.getByTestId('sidebar-session').filter({ hasText: A_TITLE })).toBeVisible()
    await expect(group.getByTestId('sidebar-session').filter({ hasText: B_TITLE })).toBeVisible()
  }

  // Screen of A: its own conversation unmarked, B's marked with the project name.
  await openProject(page, A)
  const onA = page.getByTestId('group-section').filter({ hasText: GROUP })
  await expect(onA.getByTestId('group-count')).toContainText('2 conversas')
  await expect(onA).toContainText(A_TITLE)
  await expect(onA).toContainText(B_TITLE)
  await expect(onA).toContainText(B)

  // Screen of B shows the same group, created elsewhere.
  await openProject(page, B)
  const onB = page.getByTestId('group-section').filter({ hasText: GROUP })
  await expect(onB.getByTestId('group-count')).toContainText('2 conversas')
  await expect(onB).toContainText(A_TITLE)
  await expect(onB).toContainText(A)
})

test('remover pelo × da barra lateral: foco, Esc, confirmação e conversas soltas', async ({ page }) => {
  await seedGroup(page)
  const nav = sidebar(page)
  const remove = nav.getByTestId('sidebar-group-remove').first()
  const confirm = nav.getByTestId('group-confirm-remove')

  // Esc cancels and returns focus to the × that opened the dialog; the dialog starts on Cancelar.
  await remove.hover()
  await remove.click()
  await expect(confirm).toBeVisible()
  await expect(confirm.getByTestId('group-confirm-cancel')).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(confirm).toHaveCount(0)
  await expect(remove).toBeFocused()

  // Cancelar does the same.
  await remove.click()
  await confirm.getByTestId('group-confirm-cancel').click()
  await expect(confirm).toHaveCount(0)
  await expect(nav.getByTestId('sidebar-group')).toHaveCount(2)

  // Confirm: the text counts conversations and projects; nothing is deleted.
  await remove.click()
  await expect(confirm).toContainText(`Remover o agrupador ${GROUP}?`)
  await expect(confirm).toContainText('As 2 conversas, de 2 projetos, voltam a ficar soltas; nenhuma é apagada.')
  await confirm.getByTestId('group-confirm-ok').click()

  await expect(nav.getByTestId('sidebar-group')).toHaveCount(0)
  await expect(nav.getByText(GROUP, { exact: true })).toHaveCount(0)
  // Both conversations are still there, loose, under their projects.
  await expect(nav.getByTestId('project-session').filter({ hasText: A_TITLE })).toBeVisible()
  await expect(nav.getByTestId('project-session').filter({ hasText: B_TITLE })).toBeVisible()
  for (const name of [A, B]) {
    await openProject(page, name)
    await expect(page.getByTestId('group-section')).toHaveCount(0)
  }
})

test('remover pelo painel de detalhes da conversa', async ({ page }) => {
  await seedGroup(page)
  const select = await openConversation(page, B_TITLE)
  await select.selectOption({ label: `${GROUP} · ${A}` })
  const open = page.getByTestId('prop-group-remove')
  const confirm = page.getByTestId('group-confirm-remove')

  // Esc, then Cancelar: each returns focus to "Remover agrupador".
  await open.click()
  await expect(confirm.getByTestId('group-confirm-cancel')).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(confirm).toHaveCount(0)
  await expect(open).toBeFocused()
  await open.click()
  await confirm.getByTestId('group-confirm-cancel').click()
  await expect(open).toBeFocused()
  await expect(select).toHaveValue(/\d+/)

  await open.click()
  await expect(confirm).toContainText('de 2 projetos')
  await confirm.getByTestId('group-confirm-ok').click()
  await expect(select).toHaveValue('')
  await expect(open).toHaveCount(0)
  await expect(sidebar(page).getByTestId('sidebar-group')).toHaveCount(0)

  // The conversation of A was released too.
  const fromA = await openConversation(page, A_TITLE)
  await expect(fromA).toHaveValue('')
})
