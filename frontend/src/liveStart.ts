import type { Router } from 'vue-router'

/** Starts the live connection and notifications once the first route is known, except on bare pages. */
export async function startLive(router: Router, start: () => void): Promise<void> {
  await router.isReady()
  if (router.currentRoute.value.meta.bare === true) return
  start()
}
