import './migrateStorage'
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import './style.css'
import App from './App.vue'
import { createAppRouter } from './router'
import { useEventSocket } from './api/socket'
import { bindRealtime } from './stores/realtime'
import { applyUiScale, uiScale } from './uiScale'
import { applyTheme, theme } from './theme'
import { bindNotifications, bindSpecialistNotifications } from './notifications'
import { useSessionsStore } from './stores/sessions'
import { useSpecialistsStore } from './stores/specialists'
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
  // The same for the notices the agents leave; with no conversation to open, the click goes to the Inbox.
  bindSpecialistNotifications(useSpecialistsStore(), (id) => void router.push(id ? { name: 'session', params: { id } } : '/inbox'))
})

applyUiScale(uiScale.value)
applyTheme(theme.value)
app.mount('#app')
