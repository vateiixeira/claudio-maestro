import { expect, test as base } from '@playwright/test'

// Every test fails when the page logs an error or throws, even if its own checks pass.
export const test = base.extend<{ consoleErrors: string[] }>({
  consoleErrors: [
    async ({ page }, use) => {
      const errors: string[] = []
      page.on('console', (message) => {
        if (message.type() === 'error') errors.push(message.text())
      })
      page.on('pageerror', (error) => errors.push(error.message))
      await use(errors)
      expect(errors, 'erros no console do navegador').toEqual([])
    },
    { auto: true },
  ],
})

export { expect }

/** Navigate through the visible disclosure before using a secondary destination. */
export async function openNavigationGroup(page: import('@playwright/test').Page, name: string) {
  const summary = page.getByText(name, { exact: true })
  await expect(summary).toBeVisible()
  if (!await summary.evaluate(element => (element.parentElement as HTMLDetailsElement).open)) await summary.click()
}
