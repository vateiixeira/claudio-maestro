<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import ColumnResizer from '../components/session/ColumnResizer.vue'
import SessionColumn from '../components/session/SessionColumn.vue'
import ChangesPanel from '../components/git/ChangesPanel.vue'
import { useChangesPanelStore } from '../stores/changesPanel'
import { useConversationStore } from '../stores/conversation'
import { useLayoutStore } from '../stores/layout'
import HomeView from './HomeView.vue'

const route = useRoute()
const router = useRouter()
const layout = useLayoutStore()
const conversations = useConversationStore()
const changesPanel = useChangesPanelStore()

const routeSessionId = computed(() => (route.name === 'session' ? String(route.params.id) : null))

// Opening a session (menu, project page, "Nova sessão") goes through /sessions/:id.
const strip = ref<HTMLElement | null>(null)
const columnEls = new Map<string, HTMLElement>()
watch(
  routeSessionId,
  async (id) => {
    if (!id) return
    layout.open(id)
    await nextTick()
    columnEls.get(id)?.scrollIntoView?.({ behavior: 'smooth', block: 'nearest', inline: 'nearest' })
  },
  { immediate: true },
)

function close(id: string) {
  layout.close(id)
  conversations.forget(id)
  if (changesPanel.sessionId === id) changesPanel.close()
  if (routeSessionId.value === id) void router.push({ name: 'home' })
}

// Which columns are on screen, so only those are marked as seen. A column counts
// as visible only after the observer reports it; without observer support, all do.
const supportsObserver = typeof IntersectionObserver !== 'undefined'
const shown = reactive(new Set<string>())
let observer: IntersectionObserver | null = null

function isVisible(id: string): boolean {
  return !supportsObserver || shown.has(id)
}

// The strip is under v-if, so the observer is rebuilt whenever it is replaced.
watch(
  strip,
  (el) => {
    observer?.disconnect()
    observer = null
    shown.clear()
    if (!el || !supportsObserver) return
    observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          const id = (entry.target as HTMLElement).dataset.sessionId
          if (!id) continue
          if (entry.isIntersecting) shown.add(id)
          else shown.delete(id)
        }
      },
      { root: el, threshold: 0.2 },
    )
    columnEls.forEach((col) => observer!.observe(col))
  },
  { flush: 'post' },
)
onBeforeUnmount(() => observer?.disconnect())

function bindColumn(id: string, el: unknown) {
  const previous = columnEls.get(id)
  if (el instanceof HTMLElement) {
    if (previous === el) return
    if (previous) observer?.unobserve(previous)
    columnEls.set(id, el)
    observer?.observe(el)
  } else if (previous) {
    observer?.unobserve(previous)
    columnEls.delete(id)
    shown.delete(id)
  }
}
</script>

<template>
  <HomeView v-if="layout.columns.length === 0" />
  <div
    v-else
    ref="strip"
    aria-label="Sessões abertas"
    role="region"
    class="flex h-full min-w-0 overflow-x-auto overflow-y-hidden"
  >
    <template v-for="id in layout.columns" :key="id">
      <div
        :ref="(el) => bindColumn(id, el)"
        data-test="session-column"
        :data-session-id="id"
        class="h-full shrink-0"
        :style="{ width: `${layout.widthOf(id)}px` }"
      >
        <SessionColumn
          :id="id"
          :visible="isVisible(id)"
          @close="close(id)"
          @missing="close(id)"
        />
      </div>
      <ChangesPanel v-if="changesPanel.sessionId === id" :key="id" :session-id="id" />
      <ColumnResizer
        :width="layout.widthOf(id)"
        label="Ajustar largura da coluna"
        @resize="(w) => layout.setWidth(id, w)"
      />
    </template>
  </div>
</template>
