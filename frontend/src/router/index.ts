import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    component: () => import('@/layouts/AppLayout.vue'),
    children: [
      { path: '', name: 'login', component: () => import('@/pages/LoginPage.vue') },
      {
        path: '',
        component: () => import('@/layouts/MainLayout.vue'),
        children: [
          { path: 'home', name: 'home', component: () => import('@/pages/HomePage.vue') },
          { path: 'performance', name: 'performance', component: () => import('@/pages/PerformancePage.vue') },
          { path: 'performance/tasks', name: 'performance-tasks', component: () => import('@/pages/TasksPage.vue') },
          { path: 'ui', name: 'ui', component: () => import('@/pages/UIPage.vue') },
          { path: 'api', name: 'api', component: () => import('@/pages/APIPage.vue') },
        ],
      },
    ],
  },
]

export default createRouter({
  history: createWebHistory(),
  routes,
})
