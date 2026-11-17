<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, useAttrs } from 'vue'

export interface MoreMenuItem {
  id: string
  label: string
  danger?: boolean
  disabled?: boolean
}

defineOptions({ inheritAttrs: false })

defineProps<{
  /** Accessible name of the button, e.g. "Mais ações". */
  label: string
  items: MoreMenuItem[]
}>()
const emit = defineEmits<{ select: [id: string] }>()

// class and style belong to the root element; everything else (data-test, id...) to the button.
const attrs = useAttrs()
const rootAttrs = computed(() => ({ class: attrs.class, style: attrs.style }))
const buttonAttrs = computed(() => {
  const { class: _class, style: _style, ...rest } = attrs
  return rest
})

const open = ref(false)
const root = ref<HTMLElement | null>(null)
const trigger = ref<HTMLButtonElement | null>(null)
const menu = ref<HTMLElement | null>(null)

const entries = () =>
  Array.from(menu.value?.querySelectorAll<HTMLElement>('[role="menuitem"]:not([aria-disabled="true"])') ?? [])

const GAP = 4 // between the button and the panel
const MARGIN = 8 // kept free at the viewport edges

// Same approach as OptionMenu: the panel is teleported to <body> with
// position: fixed (no ancestor's overflow clips it), starts invisible, and
// place() measures it and sets the coordinates in the same tick as the focus.
// It aligns to the button's right edge (a "more" button sits at a row's end).
function place() {
  const button = trigger.value
  const panel = menu.value
  if (!button || !panel) return
  const rect = button.getBoundingClientRect()
  const viewportWidth = window.innerWidth
  const viewportHeight = window.innerHeight
  const above = rect.top - GAP - MARGIN
  const below = viewportHeight - rect.bottom - GAP - MARGIN
  const needed = panel.scrollHeight + 2
  // Prefer downward; flip up when it does not fit and there is more room above.
  const down = needed <= below || below >= above
  const left = Math.max(MARGIN, Math.min(rect.right - panel.offsetWidth, viewportWidth - panel.offsetWidth - MARGIN))
  const style = panel.style
  style.left = `${left}px`
  style.top = down ? `${rect.bottom + GAP}px` : ''
  style.bottom = down ? '' : `${viewportHeight - rect.top + GAP}px`
  style.maxHeight = `${Math.max(0, down ? below : above)}px`
  style.visibility = ''
}

async function show() {
  open.value = true
  document.addEventListener('pointerdown', onOutside)
  window.addEventListener('resize', onResize)
  window.addEventListener('scroll', onScroll, true)
  await nextTick()
  place()
  // With every item disabled the panel itself takes the focus, so Esc still works.
  const first = entries()[0]
  if (first) first.focus()
  else menu.value?.focus()
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
// panel that is about to disappear.
function hideKeepingFocus() {
  hide(!!menu.value?.contains(document.activeElement))
}
function onResize() {
  hideKeepingFocus()
}
function onScroll(event: Event) {
  const target = event.target as Node | null
  const button = trigger.value
  if (!button || (target && menu.value?.contains(target))) return
  const moved = !target || target === document || target === document.documentElement || target.contains(button)
  if (!moved) return
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

// Enter is handled here (preventDefault) so the click the browser would fire
// does not toggle a second time. Space keeps the native click.
function onTriggerKey(event: KeyboardEvent) {
  if (event.key === 'Enter' || event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault()
    if (!open.value) void show()
  }
}

function onMenuKey(event: KeyboardEvent) {
  const list = entries()
  const current = list.indexOf(document.activeElement as HTMLElement)
  let next: number | null = null
  if (list.length) {
    if (event.key === 'ArrowDown') next = (current + 1) % list.length
    else if (event.key === 'ArrowUp') next = (current - 1 + list.length) % list.length
    else if (event.key === 'Home') next = 0
    else if (event.key === 'End') next = list.length - 1
  }
  if (event.key === 'Escape') {
    // Only the menu closes: a dialog around it must not see this Esc.
    event.preventDefault()
    event.stopPropagation()
    hide()
    return
  }
  if (event.key === 'Tab') {
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

function choose(item: MoreMenuItem) {
  if (item.disabled) return
  hide()
  emit('select', item.id)
}
</script>

<template>
  <div ref="root" class="relative inline-flex" :class="rootAttrs.class" :style="rootAttrs.style">
    <button
      ref="trigger"
      type="button"
      data-test="more-menu"
      v-bind="buttonAttrs"
      :aria-label="label"
      :title="label"
      aria-haspopup="menu"
      :aria-expanded="open"
      class="inline-flex size-7 cursor-pointer items-center justify-center rounded-lg border-0 bg-transparent p-0 text-fg-subtle hover:bg-card hover:text-fg focus-visible:outline-2 focus-visible:outline-primary aria-expanded:bg-card aria-expanded:text-fg"
      @click="toggle"
      @keydown="onTriggerKey"
    >
      <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
        <circle cx="5" cy="12" r="1.8" /><circle cx="12" cy="12" r="1.8" /><circle cx="19" cy="12" r="1.8" />
      </svg>
    </button>
    <Teleport to="body">
      <div
        v-if="open"
        ref="menu"
        role="menu"
        tabindex="-1"
        :aria-label="label"
        style="position: fixed; visibility: hidden"
        class="z-[60] flex min-w-44 outline-none flex-col overflow-y-auto rounded-lg border border-line-strong bg-card p-1 shadow-lg"
        @keydown="onMenuKey"
      >
        <button
          v-for="item in items"
          :key="item.id"
          type="button"
          role="menuitem"
          data-test="more-menu-item"
          :data-id="item.id"
          :aria-disabled="item.disabled ? 'true' : undefined"
          tabindex="-1"
          class="cursor-pointer rounded-md px-2.5 py-1.5 text-left text-sm hover:bg-elevated focus:bg-elevated focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-fg-muted aria-disabled:cursor-default aria-disabled:opacity-50 aria-disabled:hover:bg-transparent"
          :class="item.danger ? 'text-diff-del-fg' : 'text-fg'"
          @click="choose(item)"
        >{{ item.label }}</button>
      </div>
    </Teleport>
  </div>
</template>
