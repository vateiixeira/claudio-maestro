import { expect, test } from './fixtures'
import { openOrganization } from './org-helpers'

// The CTO Maestro on top of Triagem and Revisor, in "Loja Demo" (scenario of scripts/e2e_server.py).

test('a árvore mostra o CTO no topo e os dois agentes abaixo dele', async ({ page }) => {
  await openOrganization(page)
  const tree = page.getByTestId('org-tree')
  await expect(tree.getByRole('list', { name: 'Agentes do projeto' }).first()).toBeVisible()
  const maestro = tree.getByTestId('org-node').filter({ hasText: 'Maestro' }).first()
  await expect(maestro.getByTestId('org-node-button').first()).toContainText('Maestro')
  const children = maestro.getByRole('list').getByTestId('org-node')
  await expect(children.getByTestId('org-node-button').filter({ hasText: 'Triagem' })).toBeVisible()
  await expect(children.getByTestId('org-node-button').filter({ hasText: 'Revisor' })).toBeVisible()
  // The tree lists exactly the three agents of the project, each once.
  await expect(tree.getByTestId('org-node')).toHaveCount(3)
})

test('cada agente mostra o estado por forma e por palavra', async ({ page }) => {
  await openOrganization(page)
  for (const name of ['Maestro', 'Revisor']) {
    const button = page.getByTestId('org-node-button').filter({ hasText: name }).first()
    const state = button.getByTestId('agent-state')
    await expect(state).toHaveAttribute('data-state', 'idle')
    await expect(state).toHaveAttribute('data-shape', 'circle')
    await expect(state).toHaveAccessibleName('Ocioso')
  }
  // Another spec may have woken Triagem (answering the decision, "Rodar agora"), so it is idle or
  // running, or waiting for the person; it is never off. Each state has its own shape and word.
  const triagem = page.getByTestId('org-node-button').filter({ hasText: 'Triagem' }).first().getByTestId('agent-state')
  await expect(triagem).toHaveAttribute('data-state', /^(idle|busy|waiting)$/)
  await expect(triagem).toHaveAttribute('data-shape', /^(circle|spinner|triangle)$/)
  await expect(triagem).toHaveAccessibleName(/^(Ocioso|Executando|Aguardando você)$/)
  // The description of each agent (from its AGENT.md) is under its name.
  await expect(page.getByTestId('org-node-description').filter({ hasText: 'Coordena o trabalho do projeto' })).toBeVisible()
})

test('abrir um agente pela árvore mostra o painel dele e volta para a organização', async ({ page }) => {
  await openOrganization(page)
  const triagem = page.getByTestId('org-node-button').filter({ hasText: 'Triagem' }).first()
  await expect(triagem).not.toHaveAttribute('aria-current', 'true')
  await triagem.click()
  const panel = page.getByTestId('agent-panel')
  await expect(panel.getByRole('heading', { level: 2, name: 'Triagem' })).toBeVisible()
  await expect(page.getByTestId('agent-description')).toContainText('Separa os chamados novos')
  await expect(triagem).toHaveAttribute('aria-current', 'true')
  await expect(page).toHaveURL(/agente=\d+/)
  // Who the agent reports to is a link to the boss.
  await expect(panel.getByTestId('agent-boss-link')).toHaveText('Maestro')
  for (const section of ['conversa', 'definicao', 'memoria', 'segredos', 'registro', 'execucoes']) {
    await expect(page.getByTestId(`agent-tab-${section}`)).toBeVisible()
  }
  await panel.getByTestId('agent-boss-link').click()
  await expect(panel.getByRole('heading', { level: 2, name: 'Maestro' })).toBeVisible()
  await page.getByTestId('org-back').click()
  await expect(page.getByTestId('agent-panel')).toHaveCount(0)
  await expect(page.getByTestId('org-tab-tarefas')).toHaveAttribute('aria-selected', 'true')
})

test('um agente novo nasce no projeto, abre no editor do AGENT.md e some ao ser excluído', async ({ page }) => {
  // "Painel Demo" has no agents, so the tree of "Loja Demo" stays as the other specs expect.
  await openOrganization(page, 'Painel Demo')
  await expect(page.getByTestId('org-tree-empty')).toBeVisible()
  await page.getByTestId('new-agent').click()
  const dialog = page.getByRole('dialog', { name: 'Novo agente' })
  await dialog.getByTestId('new-name').fill('Ana Documentação')
  await expect(dialog.getByTestId('new-slug')).toHaveValue('ana-documentacao')
  await expect(dialog.getByTestId('new-boss')).toContainText('Ninguém (topo)')
  await dialog.getByTestId('confirm-ok').click()

  const panel = page.getByTestId('agent-panel')
  await expect(panel.getByRole('heading', { level: 2, name: 'Ana Documentação' })).toBeVisible()
  await expect(page.getByTestId('agent-tab-definicao')).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByTestId('definition-text')).toHaveValue(/name: Ana Documentação/)
  await expect(page.getByTestId('org-node-button').filter({ hasText: 'Ana Documentação' })).toBeVisible()

  await panel.getByTestId('agent-delete').click()
  await page.getByRole('dialog', { name: 'Excluir Ana Documentação?' }).getByTestId('confirm-ok').click()
  await expect(page.getByTestId('org-tree-empty')).toBeVisible()
  await expect(page.getByTestId('agent-panel')).toHaveCount(0)
})
