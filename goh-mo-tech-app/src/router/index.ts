import { createRouter, createWebHistory } from '@ionic/vue-router';
import type { RouteRecordRaw } from 'vue-router';
import { authState } from '@/stores/auth.store';

const routes: RouteRecordRaw[] = [
  { path: '/', redirect: '/app/home' },
  { path: '/login', name: 'login', component: () => import('@/pages/LoginPage.vue'), meta: { public: true } },
  {
    path: '/app', component: () => import('@/layouts/TabsLayout.vue'),
    children: [
      { path: '', redirect: '/app/home' },
      { path: 'home', name: 'home', component: () => import('@/pages/HomePage.vue') },
      { path: 'live', name: 'live', component: () => import('@/pages/LivePage.vue') },
      { path: 'goats', name: 'goats', component: () => import('@/pages/GoatsPage.vue') },
      { path: 'alerts', name: 'alerts', component: () => import('@/pages/AlertsPage.vue') },
      { path: 'more', name: 'more', component: () => import('@/pages/MorePage.vue') },
    ],
  },
  { path: '/goats/:goatId', name: 'goat-detail', component: () => import('@/pages/GoatDetailPage.vue') },
  { path: '/automation', name: 'automation', component: () => import('@/pages/AutomationPage.vue') },
  { path: '/tracking', name: 'tracking', component: () => import('@/pages/TrackingPage.vue') },
  { path: '/security', name: 'security', component: () => import('@/pages/SecurityPage.vue') },
  { path: '/reports', name: 'reports', component: () => import('@/pages/ReportsPage.vue') },
  { path: '/marketplace', name: 'marketplace', component: () => import('@/pages/MarketplacePage.vue') },
  { path: '/:pathMatch(.*)*', redirect: '/app/home' },
];

const router = createRouter({ history: createWebHistory(import.meta.env.BASE_URL), routes });
router.beforeEach((to) => {
  if (!to.meta.public && !authState.token) return { name: 'login', query: { redirect: to.fullPath } };
  if (to.name === 'login' && authState.token) return { name: 'home' };
  return true;
});
export default router;
