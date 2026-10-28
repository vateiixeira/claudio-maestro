<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { errorMessage, listAnnouncements } from '../../api/http'
import { useOrgStore } from '../../stores/org'
import type { Announcement } from '../../types/org'
import AnnouncementCard from './AnnouncementCard.vue'

const props = defineProps<{ sessionId: string }>()
const org = useOrgStore()
const agent = computed(() => org.isMainSession(props.sessionId))
const pending = ref<Announcement[]>([])
const error = ref<string | null>(null)
let ticket = 0
onBeforeUnmount(() => { ticket++ })
async function load() {
  const mine = ++ticket
  const id = agent.value?.id
  if (!id) { pending.value = []; error.value = null; return }
  try {
    const fresh = await listAnnouncements(id, true)
    if (mine === ticket) { pending.value = [...fresh].reverse(); error.value = null }
  } catch (e) { if (mine === ticket) error.value = errorMessage(e) }
}
watch(() => [props.sessionId, agent.value?.id], () => { pending.value = []; void load() }, { immediate: true })
watch(() => agent.value && org.changes[agent.value.id], () => { void load() })
const when = (at: number) => new Date(at * 1000).toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
</script>

<template>
  <section v-if="agent && (pending.length || error)" aria-label="Anúncios das execuções" class="flex flex-col gap-2">
    <AnnouncementCard v-for="announcement in pending" :key="announcement.id" :announcement="{ when: when(announcement.created_at), text: announcement.text, sessionId: announcement.session_id }" />
    <p v-if="error" role="alert" class="m-0 text-sm text-diff-del-fg">Não foi possível carregar os anúncios. {{ error }} <button type="button" class="underline focus-visible:outline-2 focus-visible:outline-primary" @click="load">Tentar de novo</button></p>
  </section>
</template>
