<template>
  <div v-if="authChecked">
    <div v-if="isPublic" class="login-wrap">
      <router-view />
    </div>
    <div v-else class="layout">
      <aside class="sidebar">
        <div class="brand">OpenBox <small>OSS 面板</small></div>
        <nav class="nav">
          <router-link v-for="n in NAV" :key="n.path" :to="n.path"
                       :class="{ active: $route.path === n.path }">
            <span class="icon">{{ n.icon }}</span>{{ n.name }}
          </router-link>
        </nav>
      </aside>
      <main class="main">
        <router-view />
      </main>
    </div>
    <div v-if="toast.msg" class="toast">{{ toast.msg }}</div>
  </div>
  <div v-else class="login-wrap"><span class="muted">加载中…</span></div>
</template>

<script setup>
import { ref, computed, onMounted, provide } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NAV } from './router.js'
import { get } from './api.js'

const route = useRoute()
const router = useRouter()
const authChecked = ref(false)
const toast = ref({ msg: '' })
let toastTimer = null

function showToast(msg, ms = 2500) {
  toast.value.msg = msg
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => (toast.value.msg = ''), ms)
}
provide('toast', showToast)

const isPublic = computed(() => route.meta.public === true)

onMounted(async () => {
  try {
    const st = await get('/api/auth/status')
    if (st.has_password && !st.logged_in && !isPublic.value) {
      router.replace('/login')
    } else if (!st.has_password && route.path === '/login') {
      router.replace('/setup')
    }
  } catch (e) {
    // backend unreachable — still render so the error is visible
  }
  authChecked.value = true
})
</script>
