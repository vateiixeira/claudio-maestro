<script setup lang="ts">
import { computed } from 'vue'
import { useGroupsStore } from '../../stores/groups'
import IconGroup from '../icons/IconGroup.vue'

const props = defineProps<{ groupId?: number | null }>()
const groups = useGroupsStore()
// Unknown ids (a group this tab has not loaded yet) show nothing.
const group = computed(() => (props.groupId != null ? groups.byId(props.groupId) : undefined))
</script>

<template>
  <span
    v-if="group"
    data-test="group-tag"
    :title="`Agrupador: ${group.name}`"
    class="flex max-w-40 shrink-0 items-center gap-1 rounded-full border border-line-strong px-2 text-xs text-fg-subtle"
  ><IconGroup :size="12" class="shrink-0" /><span class="truncate">{{ group.name }}</span></span>
</template>
