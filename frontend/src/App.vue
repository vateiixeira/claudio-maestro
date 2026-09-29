<script setup lang="ts">
import { computed, onMounted, watchEffect } from 'vue'
import { RouterView } from 'vue-router'
import AppSidebar from './components/sidebar/AppSidebar.vue'
import ConnectionIndicator from './components/ConnectionIndicator.vue'
import { useEventSocket } from './api/socket'
import { loadEverything } from './stores/realtime'
import { useLayoutStore } from './stores/layout'
import { documentTitle } from './documentTitle'
import { useSessionsStore } from './stores/sessions'

const socket = useEventSocket()
const layout = useLayoutStore()
const sessions = useSessionsStore()

const waiting = computed(() => sessions.all.filter((s) => s.display_state === 'waiting').length)
watchEffect(() => { document.title = documentTitle(waiting.value) })

onMounted(() => {
  void layout.restore()
  loadEverything().catch(() => {
    // The projects store keeps the error and the sidebar shows it.
  })
})
</script>

<template>
  <div class="flex h-full bg-bg text-sm leading-[1.45] text-fg">
    <AppSidebar />
    <main class="min-w-0 flex-1 overflow-y-auto">
      <RouterView />
    </main>
    <ConnectionIndicator :status="socket.status.value" />
  </div>
</template>
