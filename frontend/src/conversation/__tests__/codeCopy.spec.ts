import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { onCodeCopyClick } from '../codeCopy'
import { renderMarkdown } from '../markdown'

function setClipboard(writeText: (t: string) => Promise<void>) {
  Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
}

// Dispatches a real click so `event.target` is set the way the browser sets it.
function click(target: Element) {
  return new Promise<void>((resolve) => {
    const root = target.closest('[data-root]')!
    root.addEventListener('click', (e) => { void onCodeCopyClick(e as MouseEvent).then(resolve) }, { once: true })
    target.dispatchEvent(new MouseEvent('click', { bubbles: true }))
  })
}

function mountBlocks(markdown: string) {
  const root = document.createElement('div')
  root.setAttribute('data-root', '')
  root.innerHTML = renderMarkdown(markdown)
  document.body.appendChild(root)
  return root
}

describe('onCodeCopyClick', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => {
    vi.useRealTimers()
    document.body.innerHTML = ''
  })

  it('copia o texto cru do código, troca o rótulo e volta depois de 1,5 s', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    setClipboard(writeText)
    const root = mountBlocks('```js\nconst a = "<b>"\n```')
    const button = root.querySelector<HTMLButtonElement>('[data-code-copy]')!
    await click(button)
    expect(writeText).toHaveBeenCalledWith('const a = "<b>"\n')
    expect(button.textContent).toBe('Copiado')
    vi.advanceTimersByTime(1400)
    expect(button.textContent).toBe('Copiado')
    vi.advanceTimersByTime(200)
    expect(button.textContent).toBe('Copiar')
  })

  it('copia só o bloco do botão clicado', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    setClipboard(writeText)
    const root = mountBlocks('```js\nfirst()\n```\n\ntexto\n\n```py\nsecond()\n```')
    const buttons = root.querySelectorAll<HTMLButtonElement>('[data-code-copy]')
    await click(buttons[1]!)
    expect(writeText).toHaveBeenCalledWith('second()\n')
  })

  it('avisa quando a cópia falha', async () => {
    setClipboard(vi.fn().mockRejectedValue(new Error('negado')))
    const root = mountBlocks('```\nx\n```')
    const button = root.querySelector<HTMLButtonElement>('[data-code-copy]')!
    await click(button)
    expect(button.textContent).toBe('Não foi possível copiar')
    vi.advanceTimersByTime(1600)
    expect(button.textContent).toBe('Copiar')
  })

  it('um segundo clique reinicia o prazo de 1,5 s', async () => {
    setClipboard(vi.fn().mockResolvedValue(undefined))
    const root = mountBlocks('```\nx\n```')
    const button = root.querySelector<HTMLButtonElement>('[data-code-copy]')!
    await click(button)
    vi.advanceTimersByTime(1000)
    await click(button)
    vi.advanceTimersByTime(1000)
    expect(button.textContent).toBe('Copiado')
    vi.advanceTimersByTime(600)
    expect(button.textContent).toBe('Copiar')
  })

  it('clique fora do botão não copia', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    setClipboard(writeText)
    const root = mountBlocks('```\nx\n```\n\ntexto solto')
    await click(root.querySelector('p')!)
    await click(root.querySelector('pre')!)
    expect(writeText).not.toHaveBeenCalled()
  })
})
