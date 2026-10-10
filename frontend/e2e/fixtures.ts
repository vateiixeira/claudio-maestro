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
