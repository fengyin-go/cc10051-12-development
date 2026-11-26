import { createRouter, createWebHistory } from 'vue-router'

import Overview from '@/views/Overview.vue'
import RecheckView from '@/views/RecheckView.vue'
import WorkbenchView from '@/views/WorkbenchView.vue'

const recheckAliases = [
  '/forensic-recheck',
  '/forensic/recheck',
  '/forensic',
  '/forensics',
  '/recalc',
  '/recalculate',
  '/quality_result/recheck',
  '/quality_result/forensic',
  '/quality_rule/recheck',
  '/quality_recheck',
]

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'overview', component: Overview },
    { path: '/recheck', name: 'forensic-recheck', component: RecheckView },
    ...recheckAliases.map((path) => ({ path, component: RecheckView })),
    { path: '/:moduleKey', name: 'module', component: WorkbenchView, props: true },
  ],
})

export default router
