import {
  createRouter,
  createWebHistory,
  type RouteRecordRaw,
  type RouterHistory,
} from 'vue-router'
import HomeView from '../views/HomeView.vue'
import NewProjectView from '../views/NewProjectView.vue'
import ProjectView from '../views/ProjectView.vue'
import SessionView from '../views/SessionView.vue'

export const routes: RouteRecordRaw[] = [
  { path: '/', name: 'home', component: HomeView },
  { path: '/projects/new', name: 'project-new', component: NewProjectView },
  {
    path: '/projects/:id(\\d+)',
    name: 'project',
    component: ProjectView,
    props: (route) => ({ id: Number(route.params.id) }),
  },
  {
    path: '/sessions/:id',
    name: 'session',
    component: SessionView,
    props: (route) => ({ id: String(route.params.id) }),
  },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

export function createAppRouter(history: RouterHistory = createWebHistory()) {
  return createRouter({ history, routes })
}
