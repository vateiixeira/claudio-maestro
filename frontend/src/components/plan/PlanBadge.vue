<script setup lang="ts">
import { computed } from 'vue'
import { planBadge, planPosition, planStopped, planVisible } from './planText'
import type { Session } from '../../types/api'

// "4/12" badge with a mini progress bar, shown next to a conversation title.
const props = defineProps<{ session: Session }>()

const plan = computed(() => (planVisible(props.session) ? props.session.plan! : null))
const stopped = computed(() => planStopped(props.session))
const percent = computed(() => (plan.value && plan.value.total > 0 ? Math.round((plan.value.done / plan.value.total) * 100) : 0))
</script>

<template>
  <span
    v-if="plan"
    data-test="plan-badge"
    role="img"
    class="inline-flex shrink-0 items-center gap-1.5 font-mono text-[11px] text-fg-muted"
    :title="planPosition(plan)"
    :aria-label="planPosition(plan)"
  >
    <span aria-hidden="true">{{ planBadge(plan) }}</span>
    <span aria-hidden="true" class="h-1 w-6 overflow-hidden rounded-full bg-line-strong">
      <span
        data-test="plan-badge-fill"
        class="block h-full rounded-full"
        :class="stopped ? 'bg-fg-muted' : 'bg-primary'"
        :style="{ width: `${percent}%` }"
      />
    </span>
  </span>
</template>
