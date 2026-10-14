<template>
  <div class="login-box">
    <div class="card">
      <h3>登录 OpenBox</h3>
      <form @submit.prevent="login">
        <label>面板密码</label>
        <input v-model="pw" type="password" autocomplete="current-password" required>
        <div style="margin-top:12px"><button :disabled="busy">登录</button></div>
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
const pw = ref('')
const err = ref('')
const busy = ref(false)

async function login() {
  busy.value = true; err.value = ''
  try {
    await post('/api/auth/login', { password: pw.value })
    router.replace('/')
  } catch (e) { err.value = e.message }
  busy.value = false
}
</script>
