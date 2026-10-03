<script setup lang="ts">
// Opens and closes a block of content without a jump: a grid that goes from 0fr to 1fr, with the content clipped
// while it moves. Closed content is not mounted (v-if), so Tab never reaches it and it costs nothing; on close it
// stays until the transition ends, and goes inert meanwhile.
defineProps<{ open: boolean }>()

function lock(el: Element) {
  ;(el as HTMLElement).inert = true
  el.setAttribute('inert', '')
}
</script>

<template>
  <Transition name="collapse" @before-leave="lock">
    <div v-if="open" class="collapse-grid">
      <div class="collapse-inner"><slot /></div>
    </div>
  </Transition>
</template>

<style scoped>
.collapse-grid {
  display: grid;
  grid-template-rows: 1fr;
}
.collapse-inner {
  min-height: 0;
}
.collapse-enter-active,
.collapse-leave-active {
  transition: grid-template-rows var(--motion-enter) var(--ease-maestro);
}
/* Clip only while it moves, so focus rings and shadows of the content are not cut when it rests. */
.collapse-enter-active > .collapse-inner,
.collapse-leave-active > .collapse-inner {
  overflow: hidden;
}
.collapse-enter-from,
.collapse-leave-to {
  grid-template-rows: 0fr;
}
</style>
