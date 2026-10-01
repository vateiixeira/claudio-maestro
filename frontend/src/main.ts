import { createApp } from 'vue'
import { createPinia } from 'pinia'
import './style.css'
import App from './App.vue'
import { createAppRouter } from './router'
import { useEventSocket } from './api/socket'
import { bindRealtime } from './stores/realtime'
import { migrateLegacyStorage } from './legacyStorage'

migrateLegacyStorage()
const app = createApp(App).use(createPinia()).use(createAppRouter())

const socket = useEventSocket()
bindRealtime(socket)
socket.connect()

app.mount('#app')
