import { expect, test } from './fixtures'
import { openAgent } from './org-helpers'

// The Registro of Triagem: three items (one waiting, one with an open PR, one discarded).
// Only the last test removes one, so it stays at the end of the file.

const row = (page: import('@playwright/test').Page, key: string) =>
  page.getByTestId('item-row').filter({ has: page.getByTestId('item-key').filter({ hasText: key }) })

test('o registro lista os itens com situação, nota e data, e conta por situação nos chips', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await openAgent(page, 'Triagem', 'registro')
  await expect(page.getByTestId('item-row')).toHaveCount(3)
  await expect(page.getByTestId('agent-tab-count')).toHaveText('3')

  const waiting = row(page, 'chamado:1042')
  await expect(waiting.getByTestId('item-status')).toHaveText('Aguardando')
  await expect(waiting.getByTestId('item-note')).toContainText('Cliente pede estorno em dobro')
  await expect(waiting.getByTestId('item-date')).not.toBeEmpty()
  await expect(row(page, 'chamado:1043').getByTestId('item-status')).toHaveText('PR aberto')
  await expect(row(page, 'chamado:1038').getByTestId('item-status')).toHaveText('Descartado')

  const chips = page.getByTestId('registry-filter')
  await expect(chips.getByRole('button', { name: /^Todos\s*3$/ })).toHaveAttribute('aria-pressed', 'true')
  for (const label of ['Aguardando', 'Descartado', 'PR aberto']) {
    await expect(chips.getByRole('button', { name: new RegExp(`^${label}\\s*1$`) })).toBeVisible()
  }
})

test('o link do item mostra o repositório e o número do PR e abre fora do app', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await openAgent(page, 'Triagem', 'registro')
  const link = row(page, 'chamado:1043').getByTestId('item-link')
  await expect(link).toHaveText(/^loja-demo\s*[·•]\s*PR #12$/)
  await expect(link).toHaveAttribute('href', 'https://github.com/exemplo/loja-demo/pull/12')
  await expect(link).toHaveAttribute('target', '_blank')
  await expect(link).toHaveAttribute('rel', /noopener/)
  await expect(row(page, 'chamado:1042').getByTestId('item-link')).toHaveCount(0)
})

test('filtrar por situação e buscar por texto reduzem a lista', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await openAgent(page, 'Triagem', 'registro')
  const chips = page.getByTestId('registry-filter')

  const waitingChip = chips.getByRole('button', { name: /^Aguardando/ })
  await waitingChip.click()
  await expect(waitingChip).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByTestId('item-row')).toHaveCount(1)
  await expect(row(page, 'chamado:1042')).toBeVisible()
  await chips.getByRole('button', { name: /^Todos/ }).click()
  await expect(page.getByTestId('item-row')).toHaveCount(3)

  const search = page.getByRole('searchbox', { name: 'Buscar no registro' })
  await search.fill('frete')
  await expect(page.getByTestId('item-row')).toHaveCount(1)
  await expect(row(page, 'chamado:1043')).toBeVisible()
  await search.fill('nada disso existe')
  await expect(page.getByTestId('registry-no-match')).toBeVisible()
  await expect(page.getByTestId('item-row')).toHaveCount(0)
  await search.fill('')
  await expect(page.getByTestId('item-row')).toHaveCount(3)
})

for (const width of [1920, 1440, 1280, 1024, 768, 430, 375]) {
  test(`a nota e o botão de remover de cada item continuam visíveis em ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await openAgent(page, 'Triagem', 'registro')
    const item = row(page, 'chamado:1043')
    await expect(item).toBeVisible()
    const itemBox = (await item.boundingBox())!
    const note = (await item.getByTestId('item-note').boundingBox())!
    expect(note.width, 'a nota tem largura para ser lida').toBeGreaterThan(60)
    const remove = item.getByRole('button', { name: 'Remover chamado:1043 do registro' })
    await expect(remove).toBeVisible()
    const box = (await remove.boundingBox())!
    expect(box.x + box.width, 'o botão fica dentro da linha').toBeLessThanOrEqual(itemBox.x + itemBox.width + 1)
    expect(box.x + box.width, 'o botão fica dentro da tela').toBeLessThanOrEqual(width)
  })
}

test('remover um item tira da lista e do contador', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await openAgent(page, 'Triagem', 'registro')
  await expect(page.getByTestId('item-row')).toHaveCount(3)
  await row(page, 'chamado:1038').getByRole('button', { name: 'Remover chamado:1038 do registro' }).click()
  await expect(row(page, 'chamado:1038')).toHaveCount(0)
  await expect(page.getByTestId('item-row')).toHaveCount(2)
  await expect(page.getByTestId('agent-tab-count')).toHaveText('2')
  await page.reload()
  await expect(page.getByTestId('item-row')).toHaveCount(2)
  await expect(row(page, 'chamado:1042')).toBeVisible()
})
