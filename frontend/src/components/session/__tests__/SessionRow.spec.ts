import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import { createAppRouter } from '../../../router'
import SessionRow from '../SessionRow.vue'
import { useProjectsStore } from '../../../stores/projects'
import { makeProject, makeSession } from '../../../test/factories'

function mountRow(available: boolean) {
  const pinia = createPinia()
  setActivePinia(pinia)
  useProjectsStore(pinia).projects = [makeProject({ id: 1, available })]
  const router = createAppRouter(createMemoryHistory())
  return mount(SessionRow, {
    props: { session: makeSession({ session_id: 's1', project_id: 1 }), showProject: true },
    global: { plugins: [pinia, router] },
  })
}

describe('linha de sessão', () => {
  it('marca a pasta indisponível do projeto', () => {
    expect(mountRow(false).find('[data-test="project-unavailable"]').text()).toBe('pasta indisponível')
  })

  it('sem marca quando a pasta existe', () => {
    expect(mountRow(true).find('[data-test="project-unavailable"]').exists()).toBe(false)
  })
})
