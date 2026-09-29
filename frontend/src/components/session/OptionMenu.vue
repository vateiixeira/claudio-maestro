<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'

export interface MenuOption {
  value: string
  label: string
  description?: string
}

const props = defineProps<{
  /** Accessible name of the button, e.g. "Modelo: Sonnet 5". */
  name: string
  text: string
  options: MenuOption[]
  selected: string | null
  title?: string
  highlight?: boolean
  disabled?: boolean
}>()
const emit = defineEmits<{ select: [value: string] }>()

const open = ref(false)
const root = ref<HTMLElement | null>(null)
const trigger = ref<HTMLButtonElement | null>(null)
const menu = ref<HTMLElement | null>(null)

const items = () => Array.from(menu.value?.querySelectorAll<HTMLElement>('[role="menuitemradio"]') ?? [])

async function show() {
  open.value = true
  document.addEventListener('pointerdown', onOutside)
  await nextTick()
  const list = items()
  const index = Math.max(0, props.options.findIndex((o) => o.value === props.selected))
  list[index]?.focus()
}

function hide(returnFocus = true) {
  open.value = false
  document.removeEventListener('pointerdown', onOutside)
  if (returnFocus) trigger.value?.focus()
}

function onOutside(event: Event) {
  if (!root.value?.contains(event.target as Node)) hide(false)
}
onBeforeUnmount(() => document.removeEventListener('pointerdown', onOutside))

function toggle() {
  if (open.value) hide()
  else void show()
}

function onTriggerKey(event: KeyboardEvent) {
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
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
    hide(false)
    return
  }
  if (next !== null) {
    event.preventDefault()
    list[next]?.focus()
  }
}

// A disabled button loses focus while the change saves; give it back afterwards.
let refocus = false
watch(() => props.disabled, (disabled) => {
  if (disabled || !refocus) return
  refocus = false
  const active = document.activeElement
  if (!active || active === document.body) void nextTick(() => trigger.value?.focus())
})

function choose(value: string) {
  hide()
  if (value !== props.selected) {
    refocus = true
    emit('select', value)
  }
}
</script>

<template>
  <div ref="root" class="relative">
    <button
      ref="trigger"
      type="button"
      :aria-label="name"
      :title="title"
      aria-haspopup="menu"
      :aria-expanded="open"
      :disabled="disabled"
      class="flex h-9 cursor-pointer items-center gap-1.5 rounded-md border bg-transparent px-2.5 text-[13px] hover:bg-card focus-visible:outline-2 focus-visible:outline-primary disabled:cursor-default disabled:opacity-60"
      :class="highlight ? 'border-secondary/60 bg-secondary/10 text-secondary' : 'border-line-strong text-fg'"
      @click="toggle"
      @keydown="onTriggerKey"
    >{{ text }}<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" class="text-fg-muted"><path d="m6 9 6 6 6-6" /></svg></button>
    <div
      v-if="open"
      ref="menu"
      role="menu"
      :aria-label="name"
      class="absolute bottom-full left-0 z-20 mb-1 flex min-w-48 flex-col rounded-lg border border-line-strong bg-elevated p-1 shadow-lg"
      @keydown="onMenuKey"
    >
      <button
        v-for="option in options"
        :key="option.value"
        type="button"
        role="menuitemradio"
        :aria-checked="option.value === selected"
        tabindex="-1"
        class="flex cursor-pointer flex-col items-start rounded-md px-2.5 py-1.5 text-left text-sm text-fg hover:bg-card focus:bg-card focus:outline-none aria-checked:text-primary-soft"
        @click="choose(option.value)"
      ><span>{{ option.label }}</span><span v-if="option.description" class="text-xs text-fg-muted">{{ option.description }}</span></button>
    </div>
  </div>
</template>
