// Route table: 15 panel pages + login/setup. Hash mode so the Flask
// catch-all can serve index.html for every route.

import Login from './views/Login.vue'
import Setup from './views/Setup.vue'
import Overview from './views/Overview.vue'
import Proxies from './views/Proxies.vue'
import Subscriptions from './views/Subscriptions.vue'
import Sites from './views/Sites.vue'
import Rulesets from './views/Rulesets.vue'
import Chains from './views/Chains.vue'
import Debug from './views/Debug.vue'
import Dns from './views/Dns.vue'
import Connections from './views/Connections.vue'
import Terminals from './views/Terminals.vue'
import Kernel from './views/Kernel.vue'
import Logs from './views/Logs.vue'
import Diagnostics from './views/Diagnostics.vue'
import Settings from './views/Settings.vue'
import Config from './views/Config.vue'

export const NAV = [
  { path: '/', name: '概览', icon: '◈' },
  { path: '/proxies', name: '代理', icon: '⇄' },
  { path: '/subscriptions', name: '订阅', icon: '📡' },
  { path: '/sites', name: '站点集', icon: '🗂' },
  { path: '/rulesets', name: '规则集', icon: '📏' },
  { path: '/chains', name: '链式代理', icon: '⛓' },
  { path: '/debug', name: '规则调试', icon: '🔍' },
  { path: '/dns', name: 'DNS', icon: '🌐' },
  { path: '/connections', name: '连接', icon: '🔌' },
  { path: '/terminals', name: '终端', icon: '💻' },
  { path: '/kernel', name: '内核', icon: '⚙' },
  { path: '/logs', name: '日志', icon: '📝' },
  { path: '/diagnostics', name: '诊断', icon: '🩺' },
  { path: '/settings', name: '设置', icon: '🔧' },
  { path: '/config', name: '配置', icon: '📄' },
]

export default [
  { path: '/login', component: Login, meta: { public: true } },
  { path: '/setup', component: Setup, meta: { public: true } },
  { path: '/', component: Overview },
  { path: '/proxies', component: Proxies },
  { path: '/subscriptions', component: Subscriptions },
  { path: '/sites', component: Sites },
  { path: '/rulesets', component: Rulesets },
  { path: '/chains', component: Chains },
  { path: '/debug', component: Debug },
  { path: '/dns', component: Dns },
  { path: '/connections', component: Connections },
  { path: '/terminals', component: Terminals },
  { path: '/kernel', component: Kernel },
  { path: '/logs', component: Logs },
  { path: '/diagnostics', component: Diagnostics },
  { path: '/settings', component: Settings },
  { path: '/config', component: Config },
  { path: '/:catchAll(.*)', redirect: '/' },
]
