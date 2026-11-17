import { expect, test } from './fixtures'

// What the browser answers for Notification.permission varies with the profile, so the page gets a
// fake Notification before it loads: the screen is then checked against a known permission.
function fakeNotification(permission: 'default' | 'denied' | 'granted') {
  return `window.Notification = class { static permission = '${permission}'; static requestPermission() { return Promise.resolve('${permission}') } }`
}

test('sem permissão, o aviso pede para ativar e o teste fica desabilitado com a explicação', async ({ page }) => {
  await page.addInitScript(fakeNotification('default'))
  await page.goto('/preferencias?aba=notificacoes')
  await expect(page.getByTestId('tab-notifications')).toHaveAttribute('aria-selected', 'true')

  const notice = page.getByTestId('notif-notice')
  await expect(notice).toContainText('Ainda não ativadas neste navegador.')
  await expect(notice.getByTestId('notif-enable')).toBeEnabled()
  await expect(page.getByTestId('notif-granted')).toHaveCount(0)

  // The test button is always there; without permission it is disabled and the hint says why.
  const test = page.getByTestId('notif-test')
  await expect(test).toBeVisible()
  await expect(test).toBeDisabled()
  await expect(test).toHaveText('Enviar um teste')
  await expect(page.locator('#notif-test-hint')).toContainText('O teste fica disponível depois de ativar.')

  // The choices stay editable, grouped by what they are about, with a sample of the notice beside them.
  await expect(page.getByTestId('notif-group')).toHaveCount(3)
  await expect(page.locator('[data-test="notif-group"][data-group="needs-you"]')).toContainText('Pedido de permissão')
  await expect(page.getByTestId('notif-preview')).toContainText('Cláudio Maestro')
  await expect(page.getByTestId('notif-sound-test')).toBeVisible()
  const finished = page.getByRole('switch', { name: 'Avisar em turno concluído' })
  const before = await finished.getAttribute('aria-checked')
  await finished.click()
  await expect(finished).not.toHaveAttribute('aria-checked', before!)
  await finished.click()
  await expect(finished).toHaveAttribute('aria-checked', before!)
})

test('com a permissão bloqueada, a tela explica e o teste continua desabilitado', async ({ page }) => {
  await page.addInitScript(fakeNotification('denied'))
  await page.goto('/preferencias?aba=notificacoes')
  await expect(page.getByTestId('notif-denied')).toContainText('bloqueadas no navegador')
  await expect(page.getByTestId('notif-enable')).toHaveCount(0)
  await expect(page.getByTestId('notif-test')).toBeDisabled()
})

test('com a permissão concedida, o aviso some e o teste fica habilitado', async ({ page }) => {
  await page.addInitScript(fakeNotification('granted'))
  await page.goto('/preferencias?aba=notificacoes')
  await expect(page.getByTestId('notif-granted')).toContainText('Notificações ativas neste navegador')
  await expect(page.getByTestId('notif-notice')).toHaveCount(0)
  await expect(page.getByTestId('notif-test')).toBeEnabled()
})
