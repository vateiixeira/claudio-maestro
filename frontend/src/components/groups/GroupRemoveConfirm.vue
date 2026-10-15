<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { errorMessage } from '../../api/http'
import { removeGroupText } from '../../groupList'
import { useGroupsStore } from '../../stores/groups'
import type { Session, SessionGroup } from '../../types/api'

// Confirmation to remove a group. `sessions` are its conversations, from any project: they are released, never deleted.
// The parent decides where focus goes after `cancel` (back to the button that opened this).
const props = defineProps<{ group: SessionGroup; sessions: Session[] }>()
const emit = defineEmits<{ cancel: []; removed: []; error: [message: string] }>()

const groups = useGroupsStore()
const removing = ref(false)
const cancelButton = ref<HTMLButtonElement | null>(null)
onMounted(() => cancelButton.value?.focus())

async function remove() {
  removing.value = true
  try {
    await groups.remove(props.group.id)
    emit('removed')
  } catch (e) {
    emit('error', errorMessage(e))
    emit('cancel')
  } finally {
    removing.value = false
  }
}
</script>

<template>
  <div
    data-test="group-confirm-remove"
    role="alertdialog"
    :aria-label="`Remover o agrupador ${group.name}?`"
    class="flex flex-col gap-2 rounded-lg border border-secondary/60 bg-card px-4 py-3"
    @keydown.esc.prevent="emit('cancel')"
  >
    <p class="m-0 text-sm font-semibold">Remover o agrupador {{ group.name }}?</p>
    <p class="m-0 text-sm text-fg-muted">{{ removeGroupText(sessions) }}</p>
    <div class="flex flex-wrap gap-2">
      <button type="button" data-test="group-confirm-ok" :disabled="removing" class="h-9 rounded-lg bg-secondary px-3 text-sm font-semibold text-secondary-fg hover:bg-secondary-soft disabled:opacity-40" @click="remove">{{ removing ? 'Removendo…' : 'Remover agrupador' }}</button>
      <button ref="cancelButton" type="button" data-test="group-confirm-cancel" class="h-9 rounded-lg border border-line-strong px-3 text-sm text-fg hover:bg-elevated" @click="emit('cancel')">Cancelar</button>
    </div>
  </div>
</template>
