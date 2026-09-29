import {
  createRouter,
  createWebHistory,
  type RouteRecordRaw,
  type RouterHistory,
} from 'vue-router'
import AllSessionsView from '../views/AllSessionsView.vue'
import NewProjectView from '../views/NewProjectView.vue'
import ProjectView from '../views/ProjectView.vue'
import WorkspaceView from '../views/WorkspaceView.vue'

export const routes: RouteRecordRaw[] = [
  // `/` shows the open session columns (or the start screen); `/sessions/:id`
  // shows the same workspace and opens that session as a column.
  { path: '/', name: 'home', component: WorkspaceView },
  { path: '/projects/new', name: 'project-new', component: NewProjectView },
  {
    path: '/projects/:id(\\d+)',
    name: 'project',
    component: ProjectView,
    props: (route) => ({ id: Number(route.params.id) }),
  },
  { path: '/sessions', name: 'sessions', component: AllSessionsView },
  {
    path: '/sessions/:id',
    name: 'session',
    component: WorkspaceView,
  },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

export function createAppRouter(history: RouterHistory = createWebHistory()) {
  return createRouter({ history, routes })
}
