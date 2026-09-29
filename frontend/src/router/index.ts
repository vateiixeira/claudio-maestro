import {
  createRouter,
  createWebHistory,
  type RouteRecordRaw,
  type RouterHistory,
} from 'vue-router'
import ConversationView from '../views/ConversationView.vue'
import ConversationsView from '../views/ConversationsView.vue'
import DashboardView from '../views/DashboardView.vue'
import InboxView from '../views/InboxView.vue'
import NewProjectView from '../views/NewProjectView.vue'
import PreferencesView from '../views/PreferencesView.vue'
import ProjectView from '../views/ProjectView.vue'

export const routes: RouteRecordRaw[] = [
  { path: '/', redirect: '/inbox' },
  { path: '/inbox', name: 'inbox', component: InboxView },
  { path: '/dashboard', name: 'dashboard', component: DashboardView },
  { path: '/sessions', name: 'sessions', component: ConversationsView },
  { path: '/sessions/:id', name: 'session', component: ConversationView, props: true },
  { path: '/projects/new', name: 'project-new', component: NewProjectView },
  {
    path: '/projects/:id(\\d+)',
    name: 'project',
    component: ProjectView,
    props: (route) => ({ id: Number(route.params.id) }),
  },
  { path: '/preferencias', name: 'preferences', component: PreferencesView },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

export function createAppRouter(history: RouterHistory = createWebHistory()) {
  return createRouter({ history, routes })
}
