<script setup lang="ts">
import { computed, ref } from 'vue'
import { errorMessage } from '../../../api/http'
import { useTasksStore } from '../../../stores/tasks'
import { AREA, BTN_PRIMARY, ERROR } from '../styles'

// Writes a comment on the task; the agents responsible are woken by the server. Ctrl+Enter sends.
const props = defineProps<{ taskId: number }>()
const tasks = useTasksStore()

const text = ref('')
const busy = ref(false)
const error = ref<string | null>(null)
const canSend = computed(() => text.value.trim().length > 0 && !busy.value)

async function send(): Promise<void> {
  if (!canSend.value) return
  busy.value = true
  error.value = null
  try {
    await tasks.comment(props.taskId, text.value.trim())
    text.value = ''
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    busy.value = false
  }
}

function onKey(event: KeyboardEvent): void {
  if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
    event.preventDefault()
    void send()
  }
}
</script>

<template>
  <form class="flex flex-col gap-2" @submit.prevent="send">
    <label class="text-xs text-fg-muted" for="task-composer-text">Comentar</label>
    <textarea id="task-composer-text" v-model="text" data-test="task-composer-text" rows="3" :class="AREA" placeholder="Escreva para o time. Ctrl+Enter envia." @keydown="onKey" />
    <p v-if="error" role="alert" :class="ERROR">{{ error }}</p>
    <div class="flex justify-end">
      <button type="submit" data-test="task-composer-submit" :class="BTN_PRIMARY" :disabled="!canSend">{{ busy ? 'Enviando…' : 'Comentar' }}</button>
    </div>
  </form>
</template>
