<script setup lang="ts">
import type { DiffLine } from '../../conversation/diff'
import { renderMarkdown } from '../../conversation/markdown'
import type { ThemeId } from '../../theme'
import DiffLines from '../conversation/DiffLines.vue'

/**
 * A sample open conversation painted with the colors of one theme: `data-theme` on the root scopes the
 * theme's variables to this block, so it can differ from the theme the app is using.
 * Decorative: inert and hidden from screen readers.
 */
defineProps<{ themeId: ThemeId }>()

const REPLY = [
  'Achei o problema em `redirectAfterLogin`: ele ignora o destino pedido quando a rota é protegida. Veja a [issue 214](https://example.com/issues/214).',
  '',
  '```ts',
  '// volta para a tela que o usuário pediu',
  'export function redirectAfterLogin(next?: string): string {',
  '  const target = next ?? "/inbox"',
  '  return isSafe(target) ? target : "/inbox"',
  '}',
  '```',
].join('\n')
// Safe: markdown-it runs with `html: false` and this text is a constant.
const html = renderMarkdown(REPLY)

const DIFF: DiffLine[] = [
  { kind: 'context', oldNo: 41, newNo: 41, text: 'export function redirectAfterLogin(next?: string): string {' },
  { kind: 'del', oldNo: 42, newNo: null, text: '  return "/inbox"' },
  { kind: 'add', oldNo: null, newNo: 42, text: '  const target = next ?? "/inbox"' },
  { kind: 'add', oldNo: null, newNo: 43, text: '  return isSafe(target) ? target : "/inbox"' },
  { kind: 'context', oldNo: 43, newNo: 44, text: '}' },
]
</script>

<template>
  <div
    :data-theme="themeId"
    data-test="theme-preview"
    aria-hidden="true"
    inert
    class="flex min-w-0 flex-col gap-3 rounded-xl border border-line bg-bg p-4 text-fg"
  >
    <div class="flex items-center gap-2.5">
      <h3 class="m-0 min-w-0 grow truncate text-[1.0625rem] leading-snug font-semibold tracking-tight">
        Corrigir o redirecionamento do login
      </h3>
      <span class="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-secondary/50 bg-secondary-tint px-2.5 py-0.5 text-xs font-medium text-secondary-soft">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3 2 20h20L12 3z" /></svg>
        Esperando você
      </span>
    </div>

    <div class="flex w-full justify-end pl-10">
      <div class="max-w-[72ch] rounded-2xl rounded-br-md border border-primary/25 bg-primary-tint px-3.5 py-2.5 text-sm leading-[1.55] text-fg">
        Depois do login o app sempre volta para a Inbox. Corrige para voltar à tela que eu abri.
      </div>
    </div>

    <div class="markdown"><div v-html="html" /></div>

    <div class="overflow-hidden rounded-lg border border-line bg-panel">
      <div class="flex items-center gap-2 border-b border-line px-3 py-2">
        <span class="cap shrink-0 text-fg-subtle">Edição</span>
        <span class="min-w-0 grow truncate font-mono text-xs text-info-soft">src/auth/redirect.ts</span>
        <span class="shrink-0 font-mono text-xs"><span class="text-diff-add-fg">+2</span> <span class="text-diff-del-fg">−1</span></span>
      </div>
      <div class="py-1.5"><DiffLines :lines="DIFF" /></div>
    </div>

    <div class="flex flex-col gap-3 rounded-xl border border-secondary/50 bg-panel p-3.5">
      <div class="flex items-center gap-2">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" class="shrink-0 text-secondary" aria-hidden="true"><path d="M12 3 2 20h20L12 3z" /><line x1="12" y1="10" x2="12" y2="14" /><line x1="12" y1="17" x2="12" y2="17.01" /></svg>
        <span class="font-semibold text-secondary-soft">Permissão para rodar</span>
        <span class="ml-auto font-mono text-xs text-secondary-soft">Bash</span>
      </div>
      <pre class="m-0 rounded-md border border-line bg-bg px-3 py-2.5 font-mono text-xs leading-relaxed text-fg">pnpm --dir frontend test</pre>
      <div class="flex gap-2">
        <span class="flex h-11 grow items-center justify-center rounded-lg bg-secondary text-sm font-semibold text-secondary-fg">Permitir uma vez</span>
        <span class="flex h-11 grow items-center justify-center rounded-lg border border-secondary/50 text-sm font-medium text-secondary-soft">Negar</span>
      </div>
    </div>

    <div class="flex items-center gap-2.5 rounded-xl border border-line-strong bg-elevated px-3.5 py-2.5">
      <span class="min-w-0 grow truncate text-sm text-fg-muted">Escreva uma mensagem…</span>
      <span class="flex h-8 shrink-0 items-center rounded-lg bg-primary px-3.5 text-sm font-semibold text-primary-fg">Enviar</span>
    </div>
  </div>
</template>
