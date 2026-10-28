<script setup lang="ts">
import { computed } from 'vue'
import TaskComment from './TaskComment.vue'
import type { Comment } from '../../../types/org'

// The conversation of a task, oldest first.
const props = defineProps<{ comments: Comment[] }>()
const ordered = computed(() => [...props.comments].sort((a, b) => a.created_at - b.created_at || a.id - b.id))
</script>

<template>
  <p v-if="comments.length === 0" data-test="thread-empty" class="m-0 text-sm text-fg-subtle">Nenhum comentário ainda.</p>
  <ol v-else aria-label="Comentários" class="m-0 flex list-none flex-col gap-3 p-0">
    <TaskComment v-for="comment in ordered" :key="comment.id" :comment="comment" />
  </ol>
</template>
