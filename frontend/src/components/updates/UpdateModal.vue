<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { renderMarkdown } from '../../conversation/markdown'
import { useUpdatesStore } from '../../stores/updates'
import IconClose from '../icons/IconClose.vue'

const COMMANDS = 'git pull\nuv sync\npnpm --dir frontend install'
const README_UPDATE = 'https://github.com/vateiixeira/claudio-maestro#atualizar'

const updates = useUpdatesStore()
const latest = computed(() => updates.state?.latest ?? null)
// Safe: markdown-it runs with `html: false`, so raw HTML in the notes is escaped.
const notesHtml = computed(() => renderMarkdown(latest.value?.notes || 'Sem notas para esta versão.'))
const published = computed(() => {
  const at = latest.value?.published_at
  return at ? new Date(at * 1000).toLocaleDateString('pt-BR', { day: 'numeric', month: 'long', year: 'numeric' }) : null
})

const dialogEl = ref<HTMLElement | null>(null)
const closeEl = ref<HTMLButtonElement | null>(null)
const copied = ref(false)
let opener: HTMLElement | null = null
let copiedTimer: ReturnType<typeof setTimeout> | undefined

onMounted(async () => {
  opener = document.activeElement instanceof HTMLElement ? document.activeElement : null
  await nextTick()
  closeEl.value?.focus()
})
onBeforeUnmount(() => {
  clearTimeout(copiedTimer)
  opener?.focus()
})

function close(): void {
  updates.closeModal()
}

async function copyCommands(): Promise<void> {
  try {
    await navigator.clipboard.writeText(COMMANDS)
    copied.value = true
    clearTimeout(copiedTimer)
    copiedTimer = setTimeout(() => (copied.value = false), 1500)
  } catch {
    // No clipboard permission: the commands stay visible to copy by hand.
  }
}

// Tab stays inside the dialog: from the last control it wraps to the first, and back.
function onKeydown(event: KeyboardEvent): void {
  if (event.key !== 'Tab' || !dialogEl.value) return
  const list = Array.from(dialogEl.value.querySelectorAll<HTMLElement>('button:not([disabled]), a[href]'))
  const first = list[0]
  const last = list[list.length - 1]
  if (!first || !last) return
  const active = document.activeElement
  if (event.shiftKey && (active === first || !dialogEl.value.contains(active))) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && (active === last || !dialogEl.value.contains(active))) {
    event.preventDefault()
    first.focus()
  }
}
</script>

<template>
  <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" @keydown.esc.prevent="close" @keydown="onKeydown" @click.self="close">
    <div
      v-if="latest"
      ref="dialogEl"
      data-test="update-modal"
      role="dialog"
      aria-modal="true"
      aria-labelledby="update-heading"
      class="flex max-h-[85vh] w-full max-w-xl flex-col rounded-xl border border-line-strong bg-panel shadow-2xl"
    >
      <header class="flex items-start gap-3 border-b border-line px-6 py-4">
        <div class="flex min-w-0 grow flex-col gap-0.5">
          <h2 id="update-heading" class="m-0 text-base font-semibold text-fg">Versão {{ latest.version }} disponível</h2>
          <p class="m-0 text-xs text-fg-muted">
            Você está na {{ updates.state?.current }}<template v-if="published"> · publicada em {{ published }}</template>
          </p>
        </div>
        <button ref="closeEl" type="button" data-test="update-close" aria-label="Fechar" class="flex size-8 shrink-0 cursor-pointer items-center justify-center rounded-md border-none bg-transparent text-fg-muted hover:bg-card" @click="close">
          <IconClose :size="14" />
        </button>
      </header>

      <div class="flex min-h-0 flex-col gap-5 overflow-y-auto px-6 py-5">
        <div data-test="update-notes" class="markdown text-sm leading-[1.6]" v-html="notesHtml" />

        <section class="flex flex-col gap-2" aria-labelledby="update-how">
          <h3 id="update-how" class="m-0 font-mono text-xs tracking-[0.08em] text-fg-muted uppercase">Para atualizar</h3>
          <div class="relative rounded-lg border border-line bg-elevated">
            <pre data-test="update-commands" class="m-0 overflow-x-auto px-3.5 py-3 font-mono text-xs text-fg">{{ COMMANDS }}</pre>
            <button type="button" data-test="update-copy" class="absolute top-2 right-2 h-7 cursor-pointer rounded-md border border-line px-2 text-xs text-fg-muted hover:bg-card hover:text-fg" @click="copyCommands">
              {{ copied ? 'Copiado' : 'Copiar' }}
            </button>
          </div>
          <p class="m-0 text-xs text-fg-muted">
            Depois, reinicie o Cláudio Maestro. Se as notas falarem do agentd, encerre-o também (as sessões em andamento caem).
            <a :href="README_UPDATE" target="_blank" rel="noopener noreferrer" class="text-fg-muted underline hover:text-fg">Como atualizar</a>
          </p>
        </section>
      </div>

      <footer class="flex flex-wrap items-center justify-end gap-2 border-t border-line px-6 py-3">
        <button type="button" data-test="update-dismiss" class="h-9 cursor-pointer rounded-lg border-none bg-transparent px-3.5 text-sm text-fg-muted hover:bg-card hover:text-fg" @click="updates.dismiss()">Dispensar</button>
        <a data-test="update-github" :href="latest.url" target="_blank" rel="noopener noreferrer" class="flex h-9 items-center rounded-lg border border-line-strong px-3.5 text-sm font-medium text-fg no-underline hover:bg-card">Ver no GitHub</a>
      </footer>
    </div>
  </div>
</template>
