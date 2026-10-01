// State of the `/` and `@` suggestion menus of the message field. The menu moves
// only through refresh(), which the textarea's input, keyup, click and select
// events call. It does not watch the text, so dictation (which changes the text by
// program) never opens it.
import { computed, nextTick, onBeforeUnmount, ref, watch, type ComputedRef, type Ref } from 'vue'
import { errorMessage, listCommands, searchFiles } from '../api/http'
import type { CommandInfo, FileMatch, SuggestionScope } from '../types/api'
import { applySuggestion, findTrigger, mentionRanges, mentionText, rankCommands, type Trigger, type TriggerKind } from './suggestions'

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
const SEARCH_DELAY_MS = 200

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
  /** Mentions inserted from the list (no trailing space), e.g. '@backend/fs.py'. */
  mentions: Ref<Set<string>>
  /** The command's argument hint while the whole text is '/name ' ('' otherwise). */
  argumentHint: ComputedRef<string>
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
  // Result of the last file search; null until the first answer since the menu opened.
  const files = ref<FileMatch[] | null>(null)
  const mentions = ref<Set<string>>(new Set())
  // Source key of the request in flight, so a stale one never blocks the new source.
  let loadingKey: string | null = null
  let searchTimer: ReturnType<typeof setTimeout> | null = null
  let searchAbort: AbortController | null = null
  let lastSeq = 0
  const scopeKey = () => JSON.stringify(options.scope())

  const kind = computed<TriggerKind | null>(() => trigger.value?.kind ?? null)
  const isOpen = computed(() => trigger.value !== null && !suppressed.value)
  const items = computed<SuggestionItem[]>(() => {
    const t = trigger.value
    if (t?.kind === 'mention') return (files.value ?? []).map(fileItem)
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
  const argumentHint = computed(() => {
    const match = /^\/([^\s/]+) $/.exec(options.text.value)
    if (!match) return ''
    return commands.value?.find((c) => c.name === match[1])?.argument_hint ?? ''
  })
  // A mention the text no longer contains (edited, deleted or sent) stops being highlighted.
  watch(options.text, (value) => {
    if (!mentions.value.size) return
    for (const mention of [...mentions.value]) {
      if (!mentionRanges(value, [mention]).length) mentions.value.delete(mention)
    }
  })

  function fileItem(file: FileMatch): SuggestionItem {
    if (file.type === 'directory') {
      return { key: `d:${file.path}`, kind: 'directory', label: file.path, detail: '', hint: '', insert: mentionText(file.path) }
    }
    const folder = file.path.slice(0, file.path.length - file.name.length).replace(/\/$/, '')
    return { key: `f:${file.path}`, kind: 'file', label: file.name, detail: folder, hint: '', insert: mentionText(file.path) }
  }

  // Drops the pending timer and any search in flight, so a late answer is ignored.
  function cancelSearch() {
    if (searchTimer !== null) clearTimeout(searchTimer)
    searchTimer = null
    searchAbort?.abort()
    searchAbort = null
    lastSeq++
  }

  function close() {
    cancelSearch()
    trigger.value = null
  }
  onBeforeUnmount(cancelSearch)

  // The selection goes back to the first item only when the list changes (kind and
  // query are handled in refresh(); a new command list here, a new file answer in
  // runSearch()), never on a plain refresh.
  watch(commands, () => {
    active.value = 0
  })
  watch(scopeKey, () => {
    commands.value = null
    files.value = null
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
        // The menu may have moved on to `@` while this was in flight; its status is not ours.
        if (kind.value === 'command') status.value = 'ready'
      }
    } catch (e) {
      if (key === scopeKey() && kind.value === 'command') {
        status.value = 'error'
        error.value = errorMessage(e)
      }
    } finally {
      if (loadingKey === key) loadingKey = null
    }
  }

  // Waits for the typing to settle; a new term replaces the pending search.
  function scheduleSearch(query: string) {
    if (searchTimer !== null) clearTimeout(searchTimer)
    searchTimer = null
    const scope = options.scope()
    if (!scope) return
    // After a failure the old message is stale as soon as the term changes.
    if (status.value === 'error') {
      status.value = 'loading'
      error.value = null
    }
    const key = scopeKey()
    searchTimer = setTimeout(() => {
      searchTimer = null
      void runSearch(scope, key, query)
    }, SEARCH_DELAY_MS)
  }

  async function runSearch(scope: SuggestionScope, key: string, query: string) {
    const seq = ++lastSeq
    searchAbort?.abort()
    const controller = new AbortController()
    searchAbort = controller
    try {
      const list = await searchFiles(scope, query, controller.signal)
      if (seq !== lastSeq || key !== scopeKey()) return
      files.value = list
      status.value = 'ready'
      error.value = null
      active.value = 0
    } catch (e) {
      if (seq !== lastSeq || key !== scopeKey()) return
      files.value = []
      status.value = 'error'
      error.value = errorMessage(e)
    } finally {
      if (searchAbort === controller) searchAbort = null
    }
  }

  function refresh() {
    const el = options.textarea.value
    // Without a source (new-conversation modal with no project) there is nothing to list.
    const found = el && options.scope() ? findTrigger(options.text.value, el.selectionStart ?? options.text.value.length) : null
    if (!found) {
      cancelSearch()
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
    const opening = !current || current.kind !== found.kind
    if (found.kind === 'mention') {
      // The first answer since the menu opened shows "loading"; later searches keep
      // the old items on screen until the new answer arrives.
      if (opening) {
        cancelSearch()
        files.value = null
        status.value = 'loading'
        error.value = null
      }
      scheduleSearch(found.query)
      return
    }
    // Loading (or retrying after an error) happens only when the menu opens, not on
    // every key typed while it is open.
    if (opening) {
      cancelSearch()
      if (commands.value) {
        status.value = 'ready'
      } else {
        // Also covers coming back from `@` while the request is still in flight.
        status.value = 'loading'
        error.value = null
        void loadCommands()
      }
    }
  }

  function choose(index: number, via: 'enter' | 'tab' | 'click') {
    const t = trigger.value
    const item = items.value[index]
    if (!t || !item) return
    // A folder picked with Tab or a click goes in without the space and the menu
    // stays open on the folder's contents; Enter finishes the mention.
    const descend = item.kind === 'directory' && via !== 'enter'
    const result = applySuggestion(options.text.value, t, item.insert, !descend)
    options.text.value = result.text
    const el = options.textarea.value
    if (el) {
      el.value = result.text
      el.setSelectionRange(result.cursor, result.cursor)
    }
    if (descend) {
      refresh()
    } else {
      if (item.kind !== 'command') mentions.value.add(item.insert)
      close()
    }
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

  return { isOpen, kind, items, active, status, error, menuId, optionId, commands, mentions, argumentHint, refresh, onKeydown, choose, close, onBlur }
}
