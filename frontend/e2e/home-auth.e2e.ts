import { expect, test } from './fixtures'

test('Início mostra a autenticação em uso e permite escolher outra sem confundir a pendência', async ({ page, request }, testInfo) => {
  const headers = { 'X-Maestro': '1' }
  const initial = await (await request.get('/api/claude-profile', { headers })).json()
  const projects = await (await request.get('/api/projects', { headers })).json()
  await page.goto('/inicio')
  const status = page.getByTestId('home-auth')
  await expect(status.getByTestId('auth-active')).toContainText(initial.active_folder)
  await expect(status.getByTestId('auth-active')).toContainText('Padrão do Claude')
  await page.screenshot({ path: testInfo.outputPath('home-auth-default.png') })
  await status.getByRole('link', { name: 'Trocar autenticação do Claude' }).click()
  await expect(page).toHaveURL(/preferencias\?aba=geral#claude-authentication$/)
  const section = page.getByRole('region', { name: 'Pasta do Claude' })
  await expect(section).toBeFocused()
  try {
    await section.getByLabel('Pasta de autenticação').fill(projects[0].path)
    await section.getByTestId('profile-save').click()
    await expect(section.getByRole('status')).toContainText('Reinicie')
    await page.getByTestId('nav-start').click()
    await expect(status.getByTestId('auth-active')).toContainText(initial.active_folder)
    await expect(status.getByTestId('auth-pending')).toContainText(projects[0].path)
    await page.setViewportSize({ width: 390, height: 844 })
    await expect(status).toBeVisible()
    await expect(status.getByTestId('auth-change')).toBeVisible()
    expect(await status.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true)
    await page.screenshot({ path: testInfo.outputPath('home-auth-mobile.png') })
  } finally {
    await request.put('/api/claude-profile', { headers: { ...headers, Origin: new URL(page.url()).origin }, data: { folder: null } })
  }
})

test('Início identifica API pela origem ativa, inclusive com pasta igual à padrão', async ({ page }) => {
  await page.route('**/api/claude-profile', route => route.fulfill({ json: {
    active_source: 'api_folder', active_folder: '/home/test/.claude', default_folder: '/home/test/.claude',
    selected_folder: null, restart_required: true,
  } }))
  await page.goto('/inicio')
  const status = page.getByTestId('home-auth')
  await expect(status.getByTestId('auth-active')).toContainText('API · pasta alternativa')
  await expect(status.getByTestId('auth-pending')).toContainText('Após reiniciar: Padrão do Claude')
})
