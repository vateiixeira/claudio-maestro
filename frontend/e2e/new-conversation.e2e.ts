import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, join, relative } from 'node:path'
import { expect, test } from './fixtures'

test('a conversa abre com a mensagem antes do primeiro envio responder e não duplica o rascunho', async ({ page, baseURL }) => {
  const headers = { 'X-Maestro': '1', Origin: baseURL! }
  let folder: string | undefined
  let projectId: number | undefined
  let releaseResponse: (() => void) | undefined
  let responseTimer: ReturnType<typeof setTimeout> | undefined
  let delivered = false
  try {
    const projects = await page.request.get('/api/projects', { headers })
    expect(projects.status()).toBe(200)
    const seeded = ((await projects.json()) as { name: string; path: string }[]).find((p) => p.name === 'Loja Demo')!
    // Only write inside the server's disposable fake home, never the real user's home.
    expect(relative(tmpdir(), seeded.path)).toMatch(/^maestro-e2e-[^/]+\/home\/projetos\/loja-demo$/)
    folder = await mkdtemp(join(dirname(seeded.path), 'nova-conversa-'))
    // A separate project lets cleanup remove the new session without changing the seeded ones.
    const created = await page.request.post('/api/projects', {
      headers, data: { name: 'Nova conversa E2E', path: folder, color: '#5294a8' },
    })
    expect(created.status()).toBe(201)
    projectId = (await created.json()).id as number

    // Focusing a composer loads the command catalog through an agent, which the E2E server
    // refuses. No slash commands are needed here; keep the actual message endpoint untouched.
    await page.route(/\/api\/(?:projects\/\d+|sessions\/[0-9a-f-]+)\/commands$/, (route) =>
      route.fulfill({ json: [] }),
    )
    await page.route('**/api/sessions/*/messages', async (route) => {
      if (route.request().method() !== 'POST') return route.fallback()
      // Forward immediately: the real E2E backend publishes the user item and refuses the agent.
      // Hold only the HTTP response, with a releasable gate so failure cleanup never leaves it hung.
      const delayed = new Promise<void>((resolve) => {
        releaseResponse = resolve
        responseTimer = setTimeout(resolve, 3_000)
      })
      const response = await route.fetch()
      await delayed
      await route.fulfill({ response })
      delivered = true
    })

    await page.goto('/inbox')
    await page.getByTestId('nav-new').click()
    const modal = page.getByTestId('new-conversation-modal')
    await modal.getByTestId('nc-project').selectOption(String(projectId))
    const prompt = 'Confira esta primeira mensagem sem esperar a conexão'
    await modal.getByTestId('nc-prompt').fill(prompt)
    const response = page.waitForResponse((r) => r.request().method() === 'POST' && /\/api\/sessions\/[^/]+\/messages$/.test(r.url()))

    const started = performance.now()
    await modal.getByRole('button', { name: 'Iniciar conversa' }).click()
    await Promise.all([
      expect(page).toHaveURL(/\/sessions\/[0-9a-f-]+$/, { timeout: 1_000 }),
      expect(page.getByTestId('user-message')).toHaveText(prompt, { timeout: 1_000 }),
    ])
    expect(performance.now() - started).toBeLessThan(1_000)
    expect(delivered, 'a mensagem já aparece enquanto a resposta HTTP está retida').toBe(false)
    await expect(modal).toHaveCount(0)

    const composer = page.getByPlaceholder('Mensagem (Ctrl+V cola imagens)', { exact: true })
    await expect(composer).toHaveValue('')
    await expect(page.getByTestId('session-error')).toContainText('O servidor de E2E não inicia o agente real.')
    expect((await response).status()).toBe(202)
    await expect(composer).toHaveValue('')
    await expect(page.getByTestId('user-message')).toHaveCount(1)

    // Mount another composer to catch a draft accidentally retained after the accepted request.
    const sessionUrl = page.url()
    await page.getByRole('link', { name: 'Cláudio Maestro', exact: true }).click()
    await expect(page).toHaveURL(/\/inbox$/)
    await page.goBack()
    await expect(page).toHaveURL(sessionUrl)
    await expect(composer).toHaveValue('')
    await expect(page.getByTestId('user-message')).toHaveText(prompt)
  } finally {
    releaseResponse?.()
    if (responseTimer) clearTimeout(responseTimer)
    await page.unrouteAll({ behavior: 'wait' })
    await page.goto('about:blank')
    if (projectId !== undefined) {
      const removed = await page.request.delete(`/api/projects/${projectId}`, { headers })
      expect(removed.status()).toBe(204)
    }
    if (folder) await rm(folder, { recursive: true, force: true })
  }
})

test('uma falha tardia do primeiro envio preserva o próximo rascunho ao voltar de outra conversa', async ({ page, baseURL, consoleErrors }) => {
  const headers = { 'X-Maestro': '1', Origin: baseURL! }
  let folder: string | undefined
  let projectId: number | undefined
  let releaseResponse: (() => void) | undefined
  let postCount = 0
  try {
    const projects = await page.request.get('/api/projects', { headers })
    expect(projects.status()).toBe(200)
    const seeded = ((await projects.json()) as { name: string; path: string }[]).find((p) => p.name === 'Loja Demo')!
    expect(relative(tmpdir(), seeded.path)).toMatch(/^maestro-e2e-[^/]+\/home\/projetos\/loja-demo$/)
    folder = await mkdtemp(join(dirname(seeded.path), 'nova-conversa-'))
    const created = await page.request.post('/api/projects', {
      headers, data: { name: 'Rascunho preservado E2E', path: folder, color: '#5294a8' },
    })
    expect(created.status()).toBe(201)
    projectId = (await created.json()).id as number

    await page.route(/\/api\/(?:projects\/\d+|sessions\/[0-9a-f-]+)\/commands$/, (route) =>
      route.fulfill({ json: [] }),
    )
    await page.route('**/api/sessions/*/messages', async (route) => {
      if (route.request().method() !== 'POST') return route.fallback()
      postCount += 1
      // No agent is started: simulate a network/service failure only after this composer unmounts.
      await new Promise<void>((resolve) => { releaseResponse = resolve })
      await route.fulfill({ status: 503, json: { detail: 'sem rede' } })
    })

    await page.goto('/inbox')
    await page.getByTestId('nav-new').click()
    const modal = page.getByTestId('new-conversation-modal')
    await modal.getByTestId('nc-project').selectOption(String(projectId))
    await modal.getByTestId('nc-prompt').fill('Primeira mensagem cujo envio ainda não respondeu')
    const response = page.waitForResponse((r) => r.request().method() === 'POST' && /\/api\/sessions\/[^/]+\/messages$/.test(r.url()))
    await modal.getByRole('button', { name: 'Iniciar conversa' }).click()
    await expect(page).toHaveURL(/\/sessions\/[0-9a-f-]+$/)
    await expect(modal).toHaveCount(0)
    await expect.poll(() => releaseResponse !== undefined).toBe(true)
    const sessionUrl = page.url()
    const composer = page.getByPlaceholder('Mensagem (Ctrl+V cola imagens)', { exact: true })
    const nextDraft = 'Próxima mensagem já escrita: preserve este texto'
    await composer.fill(nextDraft)

    // These are router links: the pending-draft map must survive the entire round trip.
    const other = page.getByRole('navigation', { name: 'Navegação' })
      .getByTestId('project-session').filter({ hasText: 'Explique a estrutura do projeto' }).first()
    const otherPath = await other.getAttribute('href')
    await other.click()
    await expect(page).toHaveURL(new URL(otherPath!, baseURL).href)
    await expect(page.getByTestId('user-message')).toHaveText('Explique a estrutura do projeto')
    await expect(composer).toHaveValue('')

    releaseResponse!()
    expect((await response).status()).toBe(503)
    // Chrome reports this deliberately refused request; remove precisely that one expected error.
    const expectedError = 'Failed to load resource: the server responded with a status of 503 (Service Unavailable)'
    await expect.poll(() => consoleErrors.filter((message) => message === expectedError).length).toBe(1)
    consoleErrors.splice(consoleErrors.indexOf(expectedError), 1)
    await expect(composer).toHaveValue('')
    await expect(page.getByTestId('chat-composer-column').getByRole('alert')).toHaveCount(0)

    await page.goBack()
    await expect(page).toHaveURL(sessionUrl)
    await expect(page.getByTestId('chat-composer-column').getByRole('alert')).toHaveText('sem rede')
    await expect(composer).toHaveValue(nextDraft)
    await page.reload()
    await expect(composer).toHaveValue(nextDraft)
    expect(postCount, 'voltar e recarregar não reenvia a primeira mensagem').toBe(1)
  } finally {
    releaseResponse?.()
    await page.unrouteAll({ behavior: 'wait' })
    await page.goto('about:blank')
    if (projectId !== undefined) {
      const removed = await page.request.delete(`/api/projects/${projectId}`, { headers })
      expect(removed.status()).toBe(204)
    }
    if (folder) await rm(folder, { recursive: true, force: true })
  }
})
