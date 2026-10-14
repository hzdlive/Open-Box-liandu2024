<template>
  <div class="login-box">
    <div class="card">
      <h3>设置面板密码</h3>
      <p class="muted">首次使用请设置一个面板密码（至少 4 位）。</p>
      <form @submit.prevent="setup">
        <label>新密码</label>
        <input v-model="pw" type="password" autocomplete="new-password" required minlength="4">
        <label style="margin-top:8px">确认密码</label>
        <input v-model="pw2" type="password" autocomplete="new-password" required>
        <div style="margin-top:12px"><button :disabled="busy">设置并进入</button></div>
      </form>
      <p v-if="err" class="danger-text">{{ err }}</p>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { post } from '../api.js'

const router = useRouter()
const pw = ref(''), pw2 = ref('')
const err = ref('')
const busy = ref(false)

async function setup() {
  if (pw.value !== pw2.value) { err.value = '两次密码不一致'; return }
  busy.value = true; err.value = ''
  try {
    await post('/api/auth/password', { new: pw.value })
    await post('/api/auth/login', { password: pw.value })
    router.replace('/')
  } catch (e) { err.value = e.message }
  busy.value = false
}
</script>
