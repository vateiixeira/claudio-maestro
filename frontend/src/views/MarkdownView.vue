<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch, watchEffect } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { errorMessage, getSessionMarkdown, openInEditor } from '../api/http'
import { onCodeCopyClick } from '../conversation/codeCopy'
import { dirname, renderMarkdown, slugify } from '../conversation/markdown'
import { formatActivity } from '../format'
import type { MarkdownFile } from '../types/api'

const props = defineProps<{ id: string }>()
const route = useRoute()
const router = useRouter()

const requested = computed(() => (typeof route.query.caminho === 'string' ? route.query.caminho : ''))
const file = ref<MarkdownFile | null>(null)
const error = ref<string | null>(null)
const loading = ref(false)
const notice = ref<string | null>(null)

const shownPath = computed(() => file.value?.path ?? requested.value)
const name = computed(() => shownPath.value.split('/').pop() || 'Arquivo')
// Safe: markdown-it runs with `html: false`.
const html = computed(() =>
  file.value ? renderMarkdown(file.value.content, { sessionId: props.id, baseDir: dirname(file.value.path), reader: true }) : '',
)
const title = computed(() => {
  const heading = file.value?.content.match(/^#\s+(.+?)\s*#*\s*$/m)?.[1]
  return heading || name.value
})
watchEffect(() => { document.title = file.value ? `${title.value} · Cláudio Maestro` : 'Cláudio Maestro' })

// Drops answers of an older request when a newer one was started.
let ticket = 0
/** `refresh`: coming back to the tab; the text is swapped only when the file changed. */
async function load(refresh = false) {
  const mine = ++ticket
  const path = requested.value
  if (!path) {
    file.value = null
    error.value = 'Nenhum arquivo informado.'
    return
  }
  if (!refresh) loading.value = true
  try {
    const next = await getSessionMarkdown(props.id, path)
    if (mine !== ticket) return
    if (!refresh || next.mtime !== file.value?.mtime || next.path !== file.value?.path) file.value = next
    error.value = null
    if (!refresh) await scrollToAnchor()
  } catch (e) {
    if (mine !== ticket) return
    file.value = null
    error.value = errorMessage(e)
  } finally {
    if (mine === ticket) loading.value = false
  }
}

async function scrollToAnchor() {
  if (!route.hash) return
  await nextTick()
  let anchor = route.hash.slice(1)
  try { anchor = decodeURIComponent(anchor) } catch { /* keeps it as it came */ }
  document.getElementById(slugify(anchor))?.scrollIntoView?.({ block: 'start' })
}

watch(() => [props.id, requested.value], () => { void load() }, { immediate: true })
watch(() => route.hash, () => { void scrollToAnchor() })

function onReturn() {
  if (document.visibilityState === 'visible') void load(true)
}
onMounted(() => {
  document.addEventListener('visibilitychange', onReturn)
  window.addEventListener('focus', onReturn)
})
onBeforeUnmount(() => {
  document.removeEventListener('visibilitychange', onReturn)
  window.removeEventListener('focus', onReturn)
})

// Links to other markdown files stay in this tab, through the router.
function onClick(event: MouseEvent) {
  onCodeCopyClick(event)
  const link = (event.target as Element | null)?.closest?.('a[data-md-view]')
  if (!link || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return
  event.preventDefault()
  void router.push(link.getAttribute('href')!)
}

async function openEditor() {
  if (!file.value) return
  try {
    await openInEditor(file.value.path)
    notice.value = null
  } catch (e) {
    notice.value = errorMessage(e)
  }
}

async function copyPath() {
  try {
    await navigator.clipboard.writeText(shownPath.value)
    notice.value = 'Caminho copiado'
  } catch {
    notice.value = 'Não foi possível copiar'
  }
}
</script>

<template>
  <div class="min-h-full bg-surface text-fg">
    <header class="sticky top-0 z-10 border-b border-line bg-surface">
      <div class="mx-auto flex max-w-[80ch] flex-wrap items-center gap-x-3 gap-y-1 px-4 py-3">
        <div class="min-w-0 basis-0 grow">
          <h1 data-test="md-name" class="truncate text-sm font-semibold">{{ name }}</h1>
          <p data-test="md-path" class="truncate font-mono text-xs text-fg-subtle" :title="shownPath">{{ shownPath }}</p>
        </div>
        <span v-if="file" data-test="md-mtime" class="shrink-0 text-xs text-fg-muted">alterado {{ formatActivity(file.mtime) }}</span>
        <button
          type="button"
          data-test="md-copy-path"
          class="h-7 shrink-0 rounded-md border border-line-strong px-2.5 text-xs text-fg-muted hover:bg-card hover:text-fg focus-visible:outline-2 focus-visible:outline-primary"
          @click="copyPath"
        >Copiar caminho</button>
        <button
          v-if="file"
          type="button"
          data-test="md-open-editor"
          class="h-7 shrink-0 rounded-md border border-line-strong px-2.5 text-xs text-fg-muted hover:bg-card hover:text-fg focus-visible:outline-2 focus-visible:outline-primary"
          @click="openEditor"
        >Abrir no editor</button>
        <p v-if="notice" class="w-full text-xs text-fg-muted" aria-live="polite">{{ notice }}</p>
      </div>
    </header>
    <article class="mx-auto max-w-[80ch] px-4 py-8">
      <p v-if="loading && !file" class="text-fg-muted">Carregando…</p>
      <div v-else-if="error" data-test="md-error" role="alert" class="rounded-lg border border-line bg-panel px-4 py-3">
        <p class="font-medium">Não foi possível abrir o arquivo.</p>
        <p class="mt-1 text-fg-muted">{{ error }}</p>
        <p v-if="requested" class="mt-1 font-mono text-xs text-fg-subtle">{{ requested }}</p>
      </div>
      <div v-else-if="file" data-test="md-body" class="markdown markdown-doc text-[0.9375rem] leading-[1.7]">
        <div @click="onClick" v-html="html" />
      </div>
    </article>
  </div>
</template>
