import { expect, test } from './fixtures'

test('pasta do Claude fica pendente até reiniciar e pode voltar ao padrão', async ({ page, request }) => {
  const response = await request.get('/api/projects', { headers: { 'X-Maestro': '1' } })
  const projects = await response.json()
  const folder = projects[0].path as string
  await page.goto('/preferencias')
  const section = page.getByRole('region', { name: 'Pasta do Claude' })
  await expect(section).toContainText('Suas conversas, projetos, agentes e preferências continuam os mesmos.')
  const active = await section.getByTestId('profile-active').textContent()
  await section.getByLabel('Pasta de autenticação').fill(folder)
  await section.getByTestId('profile-save').click()
  await expect(section.getByRole('status')).toContainText('Reinicie')
  await expect(section.getByTestId('profile-active')).toHaveText(active!)
  await page.reload()
  await expect(section.getByRole('status')).toContainText('Reinicie')
  await expect(section.getByLabel('Pasta de autenticação')).toHaveValue(folder)
  const unchanged = await request.get('/api/projects', { headers: { 'X-Maestro': '1' } })
  expect(await unchanged.json()).toEqual(projects)
  await section.getByTestId('profile-reset').click()
  await expect(section.getByRole('status')).toContainText('Pasta salva')
  await expect(section.getByRole('status')).not.toContainText('Reinicie')
})
