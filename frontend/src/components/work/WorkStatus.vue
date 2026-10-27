<script setup lang="ts">
import { label } from '../../types/work'
import DisplayStateIcon from '../DisplayStateIcon.vue'
import IconCheck from '../icons/IconCheck.vue'
import IconAlert from '../icons/IconAlert.vue'
import IconClose from '../icons/IconClose.vue'
import IconCircle from '../icons/IconCircle.vue'
defineProps<{ status: string }>()
</script>
<template>
  <span class="work-status" :data-status="status">
    <DisplayStateIcon v-if="['active', 'running'].includes(status)" display="running" :size="12" />
    <IconCheck v-else-if="['done', 'completed', 'accepted'].includes(status)" :size="12" />
    <IconAlert v-else-if="['waiting', 'blocked', 'uncertain'].includes(status)" :size="12" />
    <IconClose v-else-if="['cancelled', 'failed'].includes(status)" :size="12" />
    <IconCircle v-else :size="12" />
    {{ label(status) }}
  </span>
</template>
