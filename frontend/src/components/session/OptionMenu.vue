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

const GAP = 4 // between the button and the panel
const MARGIN = 8 // kept free at the viewport edges

// The panel is teleported to <body> with position: fixed, so no ancestor's
// overflow can clip it. It starts invisible (see the template) and place()
// measures it and sets the coordinates directly on the element, so the focus
// that follows happens in the same tick.

function place() {
  const button = trigger.value
  const panel = menu.value
  if (!button || !panel) return
  const rect = button.getBoundingClientRect()
  const viewportWidth = window.innerWidth
  const viewportHeight = window.innerHeight
  const above = rect.top - GAP - MARGIN
  const below = viewportHeight - rect.bottom - GAP - MARGIN
  // scrollHeight leaves out the 1px borders.
  const needed = panel.scrollHeight + 2
  // Prefer upward (the fields sit at the bottom); else the side that fits, else the larger one.
  const up = needed <= above || (needed > below && above >= below)
  const left = Math.max(MARGIN, Math.min(rect.left, viewportWidth - panel.offsetWidth - MARGIN))
  const style = panel.style
  style.left = `${left}px`
  style.top = up ? '' : `${rect.bottom + GAP}px`
  style.bottom = up ? `${viewportHeight - rect.top + GAP}px` : ''
  style.maxHeight = `${Math.max(0, up ? above : below)}px`
  style.visibility = ''
}

async function show() {
  open.value = true
  document.addEventListener('pointerdown', onOutside)
  window.addEventListener('resize', onResize)
  window.addEventListener('scroll', onScroll, true)
  await nextTick()
  place()
  const list = items()
  const index = Math.max(0, props.options.findIndex((o) => o.value === props.selected))
  list[index]?.focus()
}

function removeListeners() {
  document.removeEventListener('pointerdown', onOutside)
  window.removeEventListener('resize', onResize)
  window.removeEventListener('scroll', onScroll, true)
}

function hide(returnFocus = true) {
  open.value = false
  removeListeners()
  if (returnFocus) trigger.value?.focus()
}

function onOutside(event: Event) {
  const target = event.target as Node
  if (!root.value?.contains(target) && !menu.value?.contains(target)) hide(false)
}
// Closing because the layout changed: the focus only moves if it was inside the
// panel that is about to disappear; otherwise it stays where the user put it.
function hideKeepingFocus() {
  hide(!!menu.value?.contains(document.activeElement))
}
function onResize() {
  hideKeepingFocus()
}
function onScroll(event: Event) {
  const target = event.target as Node | null
  const button = trigger.value
  // Scrolling the panel's own list is fine. So is anything that does not carry the
  // button along (the conversation thread following a turn, another panel): those
  // scroll all the time and must not close the menu.
  if (!button || (target && menu.value?.contains(target))) return
  const moved = !target || target === document || target === document.documentElement || target.contains(button)
  if (!moved) return
  // The button moved with its container: follow it, unless it left the screen.
  const rect = button.getBoundingClientRect()
  const visible = rect.bottom > 0 && rect.top < window.innerHeight && rect.right > 0 && rect.left < window.innerWidth
  if (visible) place()
  else hideKeepingFocus()
}
onBeforeUnmount(removeListeners)

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
    // The panel lives in <body>, outside any dialog's focus trap: put the focus back
    // on the button (no preventDefault) so the native Tab continues from there.
    hide()
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
      class="flex h-9 cursor-pointer items-center gap-1.5 rounded-md border bg-transparent px-2.5 text-[13px] focus-visible:outline-2 focus-visible:outline-primary disabled:cursor-default disabled:opacity-60"
      :class="highlight ? 'border-secondary/60 bg-secondary/10 text-secondary' : 'border-line text-fg-muted hover:text-fg'"
      @click="toggle"
      @keydown="onTriggerKey"
    >{{ text }}<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" class="text-fg-subtle"><path d="m6 9 6 6 6-6" /></svg></button>
    <Teleport to="body">
    <div
      v-if="open"
      ref="menu"
      role="menu"
      :aria-label="name"
      style="position: fixed; visibility: hidden"
      class="z-[60] flex min-w-48 flex-col overflow-y-auto rounded-lg border border-line-strong bg-elevated p-1 shadow-lg"
      @keydown="onMenuKey"
    >
      <button
        v-for="option in options"
        :key="option.value"
        type="button"
        role="menuitemradio"
        :aria-checked="option.value === selected"
        tabindex="-1"
        class="flex cursor-pointer flex-col items-start rounded-md px-2.5 py-1.5 text-left text-sm text-fg hover:bg-card focus:bg-card focus:outline-none aria-checked:text-fg aria-checked:font-semibold"
        @click="choose(option.value)"
      ><span>{{ option.label }}</span><span v-if="option.description" class="text-xs text-fg-subtle">{{ option.description }}</span></button>
    </div>
    </Teleport>
  </div>
</template>
