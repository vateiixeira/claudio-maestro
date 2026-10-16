import { expect, test } from './fixtures'
import type { Page } from '@playwright/test'

const TERM = 'tarefa automaticamente'

// O índice se enche em segundo plano logo depois da primeira sincronização: digita de novo até o trecho aparecer.
async function searchUntilSnippet(page: Page, term: string) {
  const input = page.getByTestId('search-input')
  await expect(async () => {
    await input.fill('')
    await input.fill(term)
    await expect(page.getByTestId('search-snippet').first()).toBeVisible({ timeout: 1500 })
  }).toPass({ timeout: 20_000 })
}

async function openHit(page: Page) {
  await page.goto('/sessions')
  await searchUntilSnippet(page, TERM)
  await page.getByTestId('search-snippet').first().click()
  await expect(page.locator('[data-item-id][data-highlighted="true"]')).toBeVisible()
}

test('a busca ignora acento e maiúsculas e trata o termo como frase', async ({ page }) => {
  await page.goto('/sessions')
  await searchUntilSnippet(page, TERM)
  const input = page.getByTestId('search-input')
  for (const variant of ['TAREFA AUTOMATICAMENTE', 'tarefa automáticamente', 'Tarefa   Automaticamente']) {
    await input.fill(variant)
    await expect(page.getByTestId('search-snippet').first()).toBeVisible()
    await expect(page.getByTestId('search-snippet').first().locator('mark')).toHaveText(/tarefa\s+autom/i)
  }
})

test('termos com sintaxe de busca não quebram nem dão erro do servidor', async ({ page }) => {
  const statuses: number[] = []
  page.on('response', (response) => {
    if (response.url().includes('/api/sessions/search')) statuses.push(response.status())
  })
  await page.goto('/sessions')
  const input = page.getByTestId('search-input')
  for (const term of ['"', 'tarefa "auto', '*', 'tar*', 'NEAR', 'a NEAR b', 'foo:bar', '-x', 'AND', '(', '^', "it's", '<b>', '<script>alert(1)</script>', '%', '\\']) {
    await input.fill(term)
    await expect(page.getByRole('list', { name: 'Resultados da busca' })).toBeVisible()
    await expect(page.getByRole('alert')).toHaveCount(0)
  }
  expect(statuses.length).toBeGreaterThan(0)
  expect(statuses.filter((status) => status >= 400)).toEqual([])
})

test('termo curto não procura no conteúdo e termo de espaços não busca', async ({ page }) => {
  await page.goto('/sessions')
  await searchUntilSnippet(page, TERM)
  const input = page.getByTestId('search-input')
  await input.fill('zq')
  await expect(page.getByText('Nenhuma sessão encontrada')).toBeVisible()
  await expect(page.getByTestId('search-snippet')).toHaveCount(0)
  await input.fill('   ')
  await expect(page.getByRole('list', { name: 'Resultados da busca' })).toHaveCount(0)
})

test('o trecho fica dentro do menu lateral', async ({ page }) => {
  await page.goto('/sessions')
  await searchUntilSnippet(page, TERM)
  const snippet = page.getByTestId('search-snippet').first()
  const list = page.getByRole('list', { name: 'Resultados da busca' })
  const [s, l] = [await snippet.boundingBox(), await list.boundingBox()]
  expect(s!.x).toBeGreaterThanOrEqual(l!.x)
  expect(s!.x + s!.width).toBeLessThanOrEqual(l!.x + l!.width)
  const scrolls = await list.evaluate((el) => el.scrollWidth > el.clientWidth)
  expect(scrolls).toBe(false)
})

test('o trecho fica em no máximo duas linhas', async ({ page }) => {
  await page.goto('/sessions')
  await searchUntilSnippet(page, TERM)
  const lines = await page.getByTestId('search-snippet').first().evaluate((el) => {
    const style = getComputedStyle(el)
    return el.getBoundingClientRect().height / parseFloat(style.lineHeight)
  })
  expect(lines).toBeLessThanOrEqual(2.1)
})

test('o termo destacado tem contraste legível em todos os temas', async ({ page }) => {
  await page.goto('/preferencias')
  const ids = await page.locator('[data-test="theme-option"]').count()
  expect(ids).toBeGreaterThan(1)
  for (let i = 0; i < ids; i++) {
    await page.goto('/preferencias')
    await page.locator('[data-test="theme-option"]').nth(i).click()
    await page.goto('/sessions')
    await searchUntilSnippet(page, TERM)
    const ratio = await page.getByTestId('search-snippet').first().locator('mark').evaluate((mark) => {
      const parse = (css: string) => (css.match(/[\d.]+/g) ?? []).map(Number)
      const lum = (c: number[]) => {
        const [r, g, b] = c.slice(0, 3).map((v) => { const s = v / 255; return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4 })
        return 0.2126 * r! + 0.7152 * g! + 0.0722 * b!
      }
      const over = (top: number[], base: number[]) => {
        const a = top[3] ?? 1
        return [0, 1, 2].map((k) => top[k]! * a + base[k]! * (1 - a))
      }
      let base = [0, 0, 0]
      const chain: Element[] = []
      for (let e: Element | null = mark; e; e = e.parentElement) chain.unshift(e)
      for (const e of chain) {
        const bg = parse(getComputedStyle(e).backgroundColor)
        if (bg.length >= 3 && (bg[3] ?? 1) > 0) base = over(bg, base)
      }
      const fg = parse(getComputedStyle(mark).color)
      const [a, b] = [lum(fg), lum(base)]
      return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05)
    })
    expect(ratio, `contraste do tema ${i}`).toBeGreaterThanOrEqual(4.5)
  }
})

for (const size of [{ width: 1280, height: 720 }, { width: 900, height: 420 }, { width: 800, height: 500 }]) {
  test(`o salto vence a rolagem ao fim e deixa a mensagem à vista (${size.width}x${size.height})`, async ({ page }) => {
    await page.setViewportSize(size)
    for (let round = 0; round < 4; round++) {
      await openHit(page)
      const message = page.locator('[data-item-id][data-highlighted="true"]')
      await expect(message).toContainText(TERM)
      await expect(message).toBeInViewport()
      await expect(page.getByTestId('turn-entry').getByText('Resposta de enchimento 20.')).not.toBeInViewport()
      await expect(page).toHaveURL(/\/sessions\/[0-9a-f-]+$/)
    }
  })
}

test('recarregar a conversa não salta de novo e voltar não reabre o salto', async ({ page }) => {
  await openHit(page)
  await page.reload()
  await expect(page.getByTestId('turn-entry').first()).toBeVisible()
  await expect(page.locator('[data-highlighted="true"]')).toHaveCount(0)
  await expect(page.getByTestId('find-missed')).toHaveCount(0)
  await page.goBack()
  await expect(page).toHaveURL(/\/sessions$/)
  await page.goForward()
  await expect(page).toHaveURL(/\/sessions\/[0-9a-f-]+$/)
  await expect(page.locator('[data-highlighted="true"]')).toHaveCount(0)
})

test('abrir uma conversa sem find não destaca nada', async ({ page }) => {
  await page.goto('/sessions')
  await page.getByText('Como configuro a jornada do funil?').first().click()
  await expect(page).toHaveURL(/\/sessions\/[0-9a-f-]+$/)
  await expect(page.getByTestId('turn-entry').first()).toBeVisible()
  await expect(page.locator('[data-highlighted="true"]')).toHaveCount(0)
  await expect(page.getByTestId('find-missed')).toHaveCount(0)
})

test('o resultado abre pelo teclado: Enter no campo e Escape limpa', async ({ page }) => {
  await page.goto('/sessions')
  await page.keyboard.press('Control+k')
  await expect(page.getByTestId('search-input')).toBeFocused()
  await searchUntilSnippet(page, TERM)
  await page.getByTestId('search-input').press('Enter')
  const message = page.locator('[data-item-id][data-highlighted="true"]')
  await expect(message).toContainText(TERM)
  await expect(message).toBeInViewport()
  await page.getByTestId('search-input').focus()
  await page.keyboard.press('Escape')
  await expect(page.getByTestId('search-input')).toHaveValue('')
  await expect(page.getByTestId('search-result')).toHaveCount(0)
})

test('Tab leva ao resultado e Enter abre no trecho', async ({ page }) => {
  await page.goto('/sessions')
  await searchUntilSnippet(page, TERM)
  await page.getByTestId('search-input').focus()
  await page.keyboard.press('Tab') // limpar? o campo type=search pode ter botão
  const focused = await page.evaluate(() => document.activeElement?.getAttribute('data-test'))
  if (focused !== 'search-result') await page.keyboard.press('Tab')
  await expect(page.getByTestId('search-result').first()).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(page.locator('[data-item-id][data-highlighted="true"]')).toContainText(TERM)
})

test('a busca por título continua achando e abre a conversa', async ({ page }) => {
  await page.goto('/sessions')
  const input = page.getByTestId('search-input')
  await input.fill('estrutura do projeto')
  const result = page.getByTestId('search-result').first()
  await expect(result).toContainText('Explique a estrutura do projeto')
  await result.click()
  await expect(page).toHaveURL(/\/sessions\/[0-9a-f-]+$/)
  await expect(page.getByTestId('turn-entry').first()).toBeVisible()
  await input.fill('zzzz sem resultado')
  await expect(page.getByText('Nenhuma sessão encontrada')).toBeVisible()
})

test('abrir o mesmo resultado de novo, já dentro da conversa, salta outra vez', async ({ page }) => {
  await openHit(page)
  const message = page.locator('[data-item-id][data-highlighted="true"]')
  await expect(message).toHaveCount(0) // o destaque some sozinho
  // Vai ao fim da conversa e procura de novo.
  await page.getByTestId('turn-entry').getByText('Resposta de enchimento 20.').scrollIntoViewIfNeeded()
  await expect(page.getByTestId('turn-entry').getByText('Resposta de enchimento 20.')).toBeInViewport()
  await searchUntilSnippet(page, TERM)
  await page.getByTestId('search-snippet').first().click()
  await expect(message).toContainText(TERM)
  await expect(message).toBeInViewport()
  await expect(page.getByTestId('turn-entry').getByText('Resposta de enchimento 20.')).not.toBeInViewport()
  await expect(page).toHaveURL(/\/sessions\/[0-9a-f-]+$/)
})

test('termo só numa mensagem fora das 500 carregadas mostra o aviso na tela e deixa a conversa no fim', async ({ page }) => {
  await page.goto('/sessions')
  await searchUntilSnippet(page, 'xilofone-arquivado')
  await page.getByTestId('search-snippet').first().click()
  await expect(page).toHaveURL(/\/sessions\/[0-9a-f-]+$/)
  const notice = page.getByTestId('find-missed')
  await expect(notice).toBeVisible()
  await expect(notice).toBeInViewport()
  await expect(page.locator('[data-highlighted="true"]')).toHaveCount(0)
  // A conversa ficou no fim: a última resposta está à vista e o botão de ir ao fim não aparece.
  await expect(page.getByTestId('turn-entry').getByText('Resposta de enchimento 260.')).toBeInViewport()
  await expect(page.getByTestId('jump-to-end')).toHaveCount(0)
})
