import {
  createRouter,
  createWebHistory,
  type RouteRecordRaw,
  type RouterHistory,
} from 'vue-router'
import ConversationView from '../views/ConversationView.vue'
import AllSessionsView from '../views/AllSessionsView.vue'
import NewProjectView from '../views/NewProjectView.vue'
import PreferencesView from '../views/PreferencesView.vue'
import ProjectView from '../views/ProjectView.vue'
import WorkspaceView from '../views/WorkspaceView.vue'

export const routes: RouteRecordRaw[] = [
  // `/` shows the open session columns (or the start screen); `/sessions/:id`
  // is the single-conversation page.
  { path: '/', name: 'home', component: WorkspaceView },
  { path: '/projects/new', name: 'project-new', component: NewProjectView },
  {
    path: '/projects/:id(\\d+)',
    name: 'project',
    component: ProjectView,
    props: (route) => ({ id: Number(route.params.id) }),
  },
  { path: '/preferencias', name: 'preferences', component: PreferencesView },
  // Provisional: Tasks 8 and 10 replace these views.
  { path: '/inbox', name: 'inbox', component: () => import('../views/HomeView.vue') },
  { path: '/dashboard', name: 'dashboard', component: () => import('../views/HomeView.vue') },
  { path: '/sessions', name: 'sessions', component: AllSessionsView },
  {
    path: '/sessions/:id',
    name: 'session',
    component: ConversationView,
    props: true,
  },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

export function createAppRouter(history: RouterHistory = createWebHistory()) {
  return createRouter({ history, routes })
}
