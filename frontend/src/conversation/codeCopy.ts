const RESET_MS = 1500
const timers = new WeakMap<HTMLElement, ReturnType<typeof setTimeout>>()

// Delegated click handler for the copy buttons that `renderMarkdown` puts in fenced code blocks.
export async function onCodeCopyClick(event: MouseEvent): Promise<void> {
  const target = event.target
  if (!(target instanceof Element)) return
  const button = target.closest<HTMLElement>('[data-code-copy]')
  if (!button) return
  const code = button.closest('.code-block')?.querySelector('pre code')
  if (!code) return

  let label: string
  try {
    await navigator.clipboard.writeText(code.textContent ?? '')
    label = 'Copiado'
  } catch {
    label = 'Não foi possível copiar'
  }
  button.textContent = label
  clearTimeout(timers.get(button))
  timers.set(
    button,
    setTimeout(() => {
      button.textContent = 'Copiar'
    }, RESET_MS),
  )
}
