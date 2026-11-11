import { mkdirSync, realpathSync, rmSync, writeFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { expect, test } from './fixtures'

test('diff abre amplo no modal, cabe no celular e devolve o foco com Esc', async ({ page, request }) => {
  const response = await request.get('/api/projects', { headers: { 'X-Maestro': '1' } })
  const data = (await response.json() as { id: number; name: string; path: string }[]).find(project => project.name === 'Alterações Demo')!
  const root = realpathSync(data.path)
  expect(root).toContain('/maestro-e2e-')
  const name = 'e2e-modal-exclusivo.txt'
  const file = join(root, name)
  writeFileSync(file, 'Primeira linha do diff\nSegunda linha do diff\n', { flag: 'wx' })
  const output = resolve('..', 'docs/design/2026-11-11-project-layout/implemented')
  mkdirSync(output, { recursive: true })
  try {
    await page.goto(`/projects/${data.id}?visao=git`)
    const row = page.getByTestId('scm-file').filter({ hasText: name })
    const open = row.getByTestId('file-open')
    for (const width of [1440, 360]) {
      await page.setViewportSize({ width, height: 1000 })
      await open.click()
      const dialog = page.getByRole('dialog')
      await expect(dialog).toBeVisible()
      await expect(page.getByTestId('scm-diff-close')).toBeFocused()
      await expect(dialog).toContainText(name)
      await expect(dialog.locator('[data-test="diff-line"][data-kind="add"]').first()).toContainText('Primeira linha')
      const bounds = (await dialog.boundingBox())!
      expect(bounds.x).toBeGreaterThanOrEqual(0)
      expect(bounds.x + bounds.width).toBeLessThanOrEqual(width + 1)
      if (width === 1440) expect(bounds.width).toBeGreaterThanOrEqual(1000)
      await expect(page.getByTestId('scm-repo').locator('[data-test="diff-line"]')).toHaveCount(0)
      await page.keyboard.press('Tab')
      expect(await dialog.evaluate(element => element.contains(document.activeElement))).toBe(true)
      await page.screenshot({ path: join(output, `git-diff-modal-${width}.png`), fullPage: true })
      await page.keyboard.press('Escape')
      await expect(dialog).toHaveCount(0)
      await expect(open).toBeFocused()
    }
    await open.click()
    await page.getByTestId('scm-diff-close').click()
    await expect(open).toBeFocused()
    await open.click()
    await page.getByTestId('scm-diff-backdrop').click({ position: { x: 1, y: 1 } })
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await expect(open).toBeFocused()
  } finally {
    rmSync(file, { force: true })
  }
})
