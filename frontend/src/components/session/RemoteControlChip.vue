<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import type { RemoteControlState } from '../../types/api'
import IconAlert from '../icons/IconAlert.vue'

const props = defineProps<{
  state: RemoteControlState
  url: string | null
  error: string | null
  disabled?: boolean
}>()
const emit = defineEmits<{ toggle: [enabled: boolean] }>()

const STATE_WORD: Record<RemoteControlState, string> = {
  off: 'desligado',
  connecting: 'conectando',
  on: 'ligado',
  failed: 'não conectou',
  elsewhere: 'pausado',
}

const title = computed(() => {
  if (props.disabled) return 'Reabra a sessão para ligar o Remote Control'
  switch (props.state) {
    case 'off': return 'Ligar o Remote Control: a sessão aparece no app do Claude'
    case 'connecting': return 'Remote Control conectando…'
    case 'on': return 'Remote Control ativo · Clique para abrir no claude.ai ou desligar'
    case 'failed': return `Remote Control não conectou: ${props.error ?? 'motivo desconhecido'}. Tentando de novo.`
    default: return 'Remote Control pausado: a conversa está aberta em outro lugar'
  }
})
const active = computed(() => props.state === 'on')
// The address comes from the CLI: only the Claude app's own address becomes a link.
const link = computed(() => (props.url?.startsWith('https://claude.ai/') ? props.url : null))

const open = ref(false)
const root = ref<HTMLElement | null>(null)
const trigger = ref<HTMLButtonElement | null>(null)
const menu = ref<HTMLElement | null>(null)

const GAP = 4
const MARGIN = 8

// Same placement as OptionMenu: teleported to <body>, fixed, above the chip when it fits.
function place() {
  const button = trigger.value
  const panel = menu.value
  if (!button || !panel) return
  const rect = button.getBoundingClientRect()
  const above = rect.top - GAP - MARGIN
  const below = window.innerHeight - rect.bottom - GAP - MARGIN
  const needed = panel.scrollHeight + 2
  const up = needed <= above || (needed > below && above >= below)
  const style = panel.style
  style.left = `${Math.max(MARGIN, Math.min(rect.left, window.innerWidth - panel.offsetWidth - MARGIN))}px`
  style.top = up ? '' : `${rect.bottom + GAP}px`
  style.bottom = up ? `${window.innerHeight - rect.top + GAP}px` : ''
  style.maxHeight = `${Math.max(0, up ? above : below)}px`
  style.visibility = ''
}

const items = () => Array.from(menu.value?.querySelectorAll<HTMLElement>('[role="menuitem"]') ?? [])

function onOutside(event: Event) {
  const target = event.target as Node
  if (!root.value?.contains(target) && !menu.value?.contains(target)) hide(false)
}
function onViewportChange() {
  hide(!!menu.value?.contains(document.activeElement))
}
function removeListeners() {
  document.removeEventListener('pointerdown', onOutside)
  window.removeEventListener('resize', onViewportChange)
  window.removeEventListener('scroll', onViewportChange, true)
}
function hide(returnFocus = true) {
  open.value = false
  removeListeners()
  if (returnFocus) trigger.value?.focus()
}
onBeforeUnmount(removeListeners)

async function show() {
  open.value = true
  document.addEventListener('pointerdown', onOutside)
  window.addEventListener('resize', onViewportChange)
  window.addEventListener('scroll', onViewportChange, true)
  await nextTick()
  place()
  items()[0]?.focus()
}

// A disabled button loses focus while the change saves; give it back afterwards.
let refocus = false
watch(() => props.disabled, (disabled) => {
  if (disabled || !refocus) return
  refocus = false
  const active = document.activeElement
  if (!active || active === document.body) void nextTick(() => trigger.value?.focus())
})

function onClick() {
  if (props.disabled) return
  if (props.state === 'off') {
    refocus = true
    emit('toggle', true)
    return
  }
  if (open.value) hide()
  else void show()
}

function onTriggerKey(event: KeyboardEvent) {
  if (props.state !== 'off' && (event.key === 'ArrowDown' || event.key === 'ArrowUp')) {
    event.preventDefault()
    void show()
  }
}

function onMenuKey(event: KeyboardEvent) {
  const list = items()
  const current = list.indexOf(document.activeElement as HTMLElement)
  let next: number | null = null
  if (event.key === 'ArrowDown') next = (current + 1) % list.length
  else if (event.key === 'ArrowUp') next = (current - 1 + list.length) % list.length
  else if (event.key === 'Home') next = 0
  else if (event.key === 'End') next = list.length - 1
  else if (event.key === 'Escape') {
    // Only the menu closes: a dialog around it must not see this Esc.
    event.preventDefault()
    event.stopPropagation()
    hide()
    return
  } else if (event.key === 'Tab') {
    // The panel lives in <body>: put the focus back on the chip so the native Tab continues from there.
    hide()
    return
  }
  if (next !== null) {
    event.preventDefault()
    list[next]?.focus()
  }
}

function turnOff() {
  hide()
  refocus = true
  emit('toggle', false)
}
</script>

<template>
  <div ref="root" class="relative">
    <button
      ref="trigger"
      type="button"
      data-test="remote-control-chip"
      :data-state="state"
      :aria-label="`Remote Control: ${STATE_WORD[state]}`"
      :title="title"
      aria-haspopup="menu"
      :aria-expanded="state === 'off' ? undefined : open"
      :disabled="disabled"
      class="flex h-9 cursor-pointer items-center gap-1.5 rounded-md border px-2.5 text-[0.8125rem] focus-visible:outline-2 focus-visible:outline-primary disabled:cursor-default disabled:opacity-60"
      :class="active ? 'border-info/60 bg-info/10 text-info-soft' : 'border-line bg-transparent text-fg-muted hover:text-fg'"
      @click="onClick"
      @keydown="onTriggerKey"
    >
      <svg v-if="state === 'connecting'" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" aria-hidden="true" class="shrink-0 motion-safe:animate-spin"><path d="M21 12a9 9 0 1 1-6.22-8.56" /></svg>
      <IconAlert v-else-if="state === 'failed'" :size="13" class="text-diff-del-fg" />
      <svg v-else width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true" class="shrink-0">
        <circle cx="12" cy="12" r="2.2" :fill="active ? 'currentColor' : 'none'" />
        <path d="M7.8 7.8a6 6 0 0 0 0 8.4M16.2 7.8a6 6 0 0 1 0 8.4" />
        <path v-if="state !== 'elsewhere'" d="M4.9 4.9a10 10 0 0 0 0 14.2M19.1 4.9a10 10 0 0 1 0 14.2" />
      </svg>
      <span>Remote Control</span>
    </button>
    <Teleport to="body">
      <div
        v-if="open"
        ref="menu"
        role="menu"
        aria-label="Remote Control"
        style="position: fixed; visibility: hidden"
        class="z-[60] flex min-w-48 flex-col overflow-y-auto rounded-lg border border-line-strong bg-card p-1 shadow-lg"
        @keydown="onMenuKey"
      >
        <a
          v-if="link"
          :href="link"
          target="_blank"
          rel="noopener noreferrer"
          role="menuitem"
          tabindex="-1"
          class="cursor-pointer rounded-md px-2.5 py-1.5 text-left text-sm text-fg no-underline hover:bg-elevated focus:bg-elevated focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-fg-muted"
          @click="hide(false)"
        >Abrir no claude.ai</a>
        <button
          type="button"
          role="menuitem"
          tabindex="-1"
          class="cursor-pointer rounded-md px-2.5 py-1.5 text-left text-sm text-fg hover:bg-elevated focus:bg-elevated focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-fg-muted"
          @click="turnOff"
        >Desligar</button>
      </div>
    </Teleport>
  </div>
</template>
