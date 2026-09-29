<script setup lang="ts">
import { onMounted } from 'vue'
import { RouterView } from 'vue-router'
import AppSidebar from './components/sidebar/AppSidebar.vue'
import ConnectionIndicator from './components/ConnectionIndicator.vue'
import { useEventSocket } from './api/socket'
import { loadEverything } from './stores/realtime'
import { useLayoutStore } from './stores/layout'

const socket = useEventSocket()
const layout = useLayoutStore()

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
