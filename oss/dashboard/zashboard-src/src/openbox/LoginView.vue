<!-- Open-Box 二开：面板密码登录页（Flask session，与旧版 UI 通用） -->
<template>
  <div class="flex min-h-screen items-center justify-center bg-base-200 p-4">
    <div class="card w-full max-w-sm bg-base-100 shadow-xl">
      <div class="card-body">
        <h2 class="card-title justify-center text-2xl">Open-Box</h2>
        <p class="text-center text-sm opacity-60">请输入面板密码</p>
        <input
          v-model="pw"
          type="password"
          placeholder="面板密码"
          class="input input-bordered w-full"
          @keyup.enter="doLogin"
        />
        <p
          v-if="err"
          class="text-sm text-error"
        >
          {{ err }}
        </p>
        <button
          class="btn btn-primary w-full"
          :disabled="busy"
          @click="doLogin"
        >
          {{ busy ? '登录中…' : '登录' }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { ObxApiError } from './api'
import { obxLogin } from './auth'

const pw = ref('')
const err = ref('')
const busy = ref(false)

async function doLogin() {
  if (!pw.value || busy.value) return
  busy.value = true
  err.value = ''
  try {
    await obxLogin(pw.value)
  } catch (e) {
    err.value = e instanceof ObxApiError ? e.message : '登录失败'
  } finally {
    busy.value = false
  }
}
</script>
