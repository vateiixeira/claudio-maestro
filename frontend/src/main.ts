import './migrateStorage'
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import './style.css'
import App from './App.vue'
import { createAppRouter } from './router'
import { useEventSocket } from './api/socket'
import { bindRealtime } from './stores/realtime'
import { applyUiScale, uiScale } from './uiScale'
import { bindNotifications } from './notifications'
import { useSessionsStore } from './stores/sessions'
import { startLive } from './liveStart'

const router = createAppRouter()
const app = createApp(App).use(createPinia()).use(router)

// The reader page (a bare route) opens no WebSocket and shows no notifications.
void startLive(router, () => {
  const socket = useEventSocket()
  bindRealtime(socket)
  socket.connect()

  // System notifications when a conversation needs the user. Permission is only asked from Preferences.
  bindNotifications(useSessionsStore(), (id) => void router.push({ name: 'session', params: { id } }))
})

applyUiScale(uiScale.value)
app.mount('#app')
