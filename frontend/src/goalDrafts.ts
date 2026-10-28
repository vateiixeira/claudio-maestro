import { reactive } from 'vue'
// Drafts belong to the selected project. They never turn into a message by opening a route.
export const goalDrafts = reactive<Record<string, string>>({})
