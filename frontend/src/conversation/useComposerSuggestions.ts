// State of the `/` (and, later, `@`) suggestion menu of the message field. The
// menu moves only through refresh(), which the textarea's input, keyup, click and
// select events call. It does not watch the text, so dictation (which changes the
// text by program) never opens it.
import { computed, nextTick, ref, watch, type ComputedRef, type Ref } from 'vue'
import { errorMessage, listCommands } from '../api/http'
import type { CommandInfo, SuggestionScope } from '../types/api'
import { applySuggestion, findTrigger, rankCommands, type Trigger, type TriggerKind } from './suggestions'

export interface SuggestionItem {
  key: string
  kind: 'command' | 'file' | 'directory'
  /** '/commit', 'fs.py', 'backend/vibing/' */
  label: string
  /** Command description, or the file's folder. */
  detail: string
  /** Command argument hint ('' otherwise). */
  hint: string
  /** '/commit', '@backend/vibing/fs.py' */
  insert: string
}

export type SuggestionStatus = 'loading' | 'ready' | 'error'

export interface ComposerSuggestionsOptions {
  textarea: Ref<HTMLTextAreaElement | null>
  text: Ref<string>
  scope: () => SuggestionScope | null
  /** After the text changed by a choice (e.g. `resize`). */
  onApplied?: () => void
}

let nextMenu = 0

export function useComposerSuggestions(options: ComposerSuggestionsOptions): {
  isOpen: ComputedRef<boolean>
  kind: ComputedRef<TriggerKind | null>
  items: ComputedRef<SuggestionItem[]>
  active: Ref<number>
  status: Ref<SuggestionStatus>
  error: Ref<string | null>
  menuId: string
  optionId: (index: number) => string
  commands: Ref<CommandInfo[] | null>
  refresh: () => void
  onKeydown: (event: KeyboardEvent) => boolean
  choose: (index: number, via: 'enter' | 'tab' | 'click') => void
  close: () => void
  onBlur: () => void
} {
  const menuId = `suggestions-${++nextMenu}`
  const trigger = ref<Trigger | null>(null)
  const suppressed = ref(false)
  const active = ref(0)
  const status = ref<SuggestionStatus>('ready')
  const error = ref<string | null>(null)
  const commands = ref<CommandInfo[] | null>(null)
  // Source key of the request in flight, so a stale one never blocks the new source.
  let loadingKey: string | null = null
  const scopeKey = () => JSON.stringify(options.scope())

  const kind = computed<TriggerKind | null>(() => trigger.value?.kind ?? null)
  const isOpen = computed(() => trigger.value !== null && !suppressed.value)
  const items = computed<SuggestionItem[]>(() => {
    const t = trigger.value
    if (!t || t.kind !== 'command' || !commands.value) return []
    return rankCommands(commands.value, t.query).map((c) => ({
      key: `c:${c.name}`,
      kind: 'command' as const,
      label: `/${c.name}`,
      detail: c.description,
      hint: c.argument_hint,
      insert: `/${c.name}`,
    }))
  })
  const optionId = (index: number) => `${menuId}-opt-${index}`

  function close() {
    trigger.value = null
  }

  // The selection goes back to the first item only when the list changes (kind and
  // query are handled in refresh(); a new command list here), never on a plain refresh.
  watch(commands, () => {
    active.value = 0
  })
  watch(scopeKey, () => {
    commands.value = null
    loadingKey = null
    close()
  })

  async function loadCommands() {
    const scope = options.scope()
    const key = scopeKey()
    if (!scope || commands.value || loadingKey === key) return
    loadingKey = key
    status.value = 'loading'
    error.value = null
    try {
      const list = await listCommands(scope)
      if (key === scopeKey()) {
        commands.value = list
        status.value = 'ready'
      }
    } catch (e) {
      if (key === scopeKey()) {
        status.value = 'error'
        error.value = errorMessage(e)
      }
    } finally {
      if (loadingKey === key) loadingKey = null
    }
  }

  function refresh() {
    const el = options.textarea.value
    let found = el ? findTrigger(options.text.value, el.selectionStart ?? options.text.value.length) : null
    // The `@` menu arrives with a later task; until then it counts as no trigger.
    if (found?.kind === 'mention') found = null
    if (!found) {
      trigger.value = null
      suppressed.value = false
      return
    }
    if (suppressed.value) return
    const current = trigger.value
    if (current && current.kind === found.kind && current.query === found.query) {
      trigger.value = found // positions may have shifted; the selection stays
      return
    }
    trigger.value = found
    active.value = 0
    // Loading (or retrying after an error) happens only when the menu opens, not on
    // every key typed while it is open.
    if (found.kind === 'command' && !current) {
      if (commands.value) status.value = 'ready'
      else void loadCommands()
    }
  }

  function choose(index: number, _via: 'enter' | 'tab' | 'click') {
    const t = trigger.value
    const item = items.value[index]
    if (!t || !item) return
    const result = applySuggestion(options.text.value, t, item.insert, true)
    options.text.value = result.text
    const el = options.textarea.value
    if (el) {
      el.value = result.text
      el.setSelectionRange(result.cursor, result.cursor)
    }
    close()
    void nextTick(() => options.onApplied?.())
  }

  function onKeydown(event: KeyboardEvent): boolean {
    if (!isOpen.value) return false
    const count = items.value.length
    switch (event.key) {
      case 'ArrowDown':
      case 'ArrowUp': {
        event.preventDefault()
        if (count) {
          const step = event.key === 'ArrowDown' ? 1 : -1
          active.value = (active.value + step + count) % count
        }
        return true
      }
      case 'Enter':
      case 'Tab': {
        if (event.shiftKey || event.isComposing || event.keyCode === 229) return false
        event.preventDefault()
        if (count) choose(active.value, event.key === 'Tab' ? 'tab' : 'enter')
        return true
      }
      case 'Escape': {
        event.preventDefault()
        event.stopPropagation()
        close()
        suppressed.value = true
        return true
      }
      default:
        return false
    }
  }

  function onBlur() {
    close()
  }

  return { isOpen, kind, items, active, status, error, menuId, optionId, commands, refresh, onKeydown, choose, close, onBlur }
}
