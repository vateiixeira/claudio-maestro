import {
  createRouter,
  createWebHistory,
  type RouteRecordRaw,
  type RouterHistory,
} from 'vue-router'
import StartView from '../views/StartView.vue'
import TasksView from '../views/TasksView.vue'
import TaskView from '../views/TaskView.vue'
import OrganizationView from '../views/OrganizationView.vue'
import ConversationView from '../views/ConversationView.vue'
import ConversationsView from '../views/ConversationsView.vue'
import DashboardView from '../views/DashboardView.vue'
import DeliveriesView from '../views/DeliveriesView.vue'
import InboxView from '../views/InboxView.vue'
import MarkdownView from '../views/MarkdownView.vue'
import NewProjectView from '../views/NewProjectView.vue'
import PreferencesView from '../views/PreferencesView.vue'
import ProjectView from '../views/ProjectView.vue'
import ProjectsView from '../views/ProjectsView.vue'

export const routes: RouteRecordRaw[] = [
  { path: '/', redirect: '/inicio' },
  { path: '/inicio', name: 'start', component: StartView },
  { path: '/tarefas', name: 'tasks', component: TasksView },
  { path: '/tarefas/:id(\\d+)', name: 'task', component: TaskView, props: true },
  { path: '/inbox', name: 'inbox', component: InboxView },
  { path: '/dashboard', name: 'dashboard', component: DashboardView },
  { path: '/sessions', name: 'sessions', component: ConversationsView },
  { path: '/entregas', name: 'deliveries', component: DeliveriesView },
  // The organization of a project's agents. `?agente=` is the agent open in the panel, `?aba=` the tab
  // (`tarefas`, `rotinas` or `execucoes`; inside an agent's panel, the panel's own tab). Without a project it picks one.
  {
    path: '/agentes/:projectId(\\d+)?',
    name: 'agents',
    component: OrganizationView,
    props: (route) => ({ projectId: route.params.projectId ? Number(route.params.projectId) : undefined }),
  },
  { path: '/sessions/:id', name: 'session', component: ConversationView, props: true },
  // Reader page of a markdown file, opened in its own tab: no sidebar, no live connection.
  { path: '/sessions/:id/ver', name: 'markdown-view', component: MarkdownView, props: true, meta: { bare: true } },
  { path: '/projects', name: 'projects', component: ProjectsView },
  { path: '/projects/new', name: 'project-new', component: NewProjectView },
  {
    path: '/projects/:id(\\d+)',
    name: 'project',
    component: ProjectView,
    // `?sessao=` is the conversation open beside the project; anything but a single string is ignored.
    props: (route) => {
      const session = route.query.sessao
      return { id: Number(route.params.id), session: typeof session === 'string' && session ? session : undefined }
    },
  },
  { path: '/preferencias', name: 'preferences', component: PreferencesView },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

export function createAppRouter(history: RouterHistory = createWebHistory()) {
  return createRouter({ history, routes })
}
