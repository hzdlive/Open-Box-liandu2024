import '@/api/http'
import '@/helper/dayjs'
import 'tippy.js/animations/scale.css'
import 'tippy.js/dist/tippy.css'
import { createApp, watch } from 'vue'
import App from './App.vue'
import { loadFonts } from './assets/load-fonts'
import './assets/main.css'
import { applyCustomThemes, applyKsuTheme } from './helper'
import { i18n } from './i18n'
import router from './router'
// Open-Box 二开：面板登录门禁 + 自动接入本机 clash API
import { checkObxAuth, needObxLogin, obxAuth } from './openbox/auth'
import { ensureOpenBoxBackend } from './openbox/backend'
import LoginView from './openbox/LoginView.vue'

const isEdge = /Edg\//.test(navigator.userAgent)

if (isEdge) {
  const originalReplaceState = history.replaceState
  history.replaceState = function (...args) {
    if (document.visibilityState === 'hidden') return
    return originalReplaceState.apply(this, args)
  }
}

applyCustomThemes()
applyKsuTheme()
loadFonts()

await checkObxAuth()

if (needObxLogin()) {
  // 面板设置了密码且未登录：只挂载登录页，登录成功后整页重载进入主应用
  const app = createApp(LoginView)
  app.use(i18n)
  app.mount('#app')
  watch(
    () => obxAuth.loggedIn,
    (v) => {
      if (v) location.reload()
    },
  )
} else {
  await ensureOpenBoxBackend()
  const app = createApp(App)
  app.use(router)
  app.use(i18n)
  app.mount('#app')
}
