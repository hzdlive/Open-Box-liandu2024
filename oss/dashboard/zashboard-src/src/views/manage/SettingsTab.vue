<!-- Open-Box 二开：共享网络 / 透明代理 / 通用设置（由旧版自研 UI 移植核心项） -->
<template>
  <div>
    <div class="mb-3 flex items-center justify-between">
      <h2 class="text-lg font-bold">{{ $t('obx.panelSettings') }}</h2>
      <button
        class="btn btn-primary btn-sm"
        :disabled="saving"
        @click="save"
      >
        {{ $t('obx.save') }}
      </button>
    </div>

    <div
      v-if="err"
      class="alert alert-error mb-3"
    >
      <span>{{ err }}</span>
    </div>
    <div
      v-if="ok"
      class="alert alert-success mb-3"
    >
      <span>{{ ok }}</span>
    </div>

    <h3 class="mb-2 font-bold">{{ $t('obx.transparent') }}</h3>
    <div class="mb-5 grid max-w-3xl grid-cols-1 gap-3 md:grid-cols-2">
      <label class="form-control">
        <span class="label-text mb-1">TUN {{ $t('obx.stack') }}</span>
        <select
          v-model="s.tun_stack"
          class="select select-bordered w-full"
        >
          <option value="mixed">mixed</option>
          <option value="gvisor">gvisor</option>
          <option value="system">system</option>
        </select>
      </label>
      <label class="form-control">
        <span class="label-text mb-1">TUN MTU</span>
        <input
          v-model="s.tun_mtu"
          class="input input-bordered w-full"
        />
      </label>
      <label class="form-control">
        <span class="label-text mb-1">{{ $t('obx.mssClamp') }}</span>
        <input
          v-model="s.mss_clamp"
          class="input input-bordered w-full"
          placeholder="0=关闭，如 1452"
        />
      </label>
      <label class="form-control">
        <span class="label-text mb-1">{{ $t('obx.bypassPorts') }}</span>
        <input
          v-model="s.bypass_ports"
          class="input input-bordered w-full"
          placeholder="21114-21119, 2233"
        />
      </label>
      <label class="flex cursor-pointer items-center gap-3 rounded-box border border-base-300/30 bg-base-100 p-3">
        <input
          v-model="quic"
          type="checkbox"
          class="toggle"
        />
        <span>
          <span class="block font-medium">{{ $t('obx.quicBlock') }}</span>
          <span class="text-sm opacity-60">{{ $t('obx.quicBlockHint') }}</span>
        </span>
      </label>
      <label class="flex cursor-pointer items-center gap-3 rounded-box border border-base-300/30 bg-base-100 p-3">
        <input
          v-model="bypassKernel"
          type="checkbox"
          class="toggle"
        />
        <span>
          <span class="block font-medium">{{ $t('obx.directBypassKernel') }}</span>
          <span class="text-sm opacity-60">{{ $t('obx.directBypassKernelHint') }}</span>
        </span>
      </label>
    </div>

    <h3 class="mb-2 font-bold">{{ $t('obx.speedtest') }}</h3>
    <div class="grid max-w-3xl grid-cols-1 gap-3 md:grid-cols-2">
      <label class="form-control">
        <span class="label-text mb-1">{{ $t('obx.speedtestUrl') }}</span>
        <input
          v-model="s.speedtest_url"
          class="input input-bordered w-full"
        />
      </label>
      <label class="form-control">
        <span class="label-text mb-1">{{ $t('obx.directSpeedtestUrl') }}</span>
        <input
          v-model="s.direct_speedtest_url"
          class="input input-bordered w-full"
        />
      </label>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ObxApiError, obxGet, obxPut } from '@/openbox/api'
import { onMounted, ref } from 'vue'

const s = ref<Record<string, string>>({})
const quic = ref(true)
const bypassKernel = ref(false)
const err = ref('')
const ok = ref('')
const saving = ref(false)

async function load() {
  err.value = ''
  try {
    s.value = await obxGet<Record<string, string>>('/api/settings')
    quic.value = s.value.quic_block === '1'
    bypassKernel.value = s.value.direct_bypass_kernel === '1'
  } catch (e) { err.value = e instanceof ObxApiError ? e.message : '加载失败' }
}

async function save() {
  saving.value = true; err.value = ''; ok.value = ''
  try {
    const body: Record<string, string> = {
      tun_stack: s.value.tun_stack, tun_mtu: s.value.tun_mtu, mss_clamp: s.value.mss_clamp,
      bypass_ports: s.value.bypass_ports, speedtest_url: s.value.speedtest_url,
      direct_speedtest_url: s.value.direct_speedtest_url,
      quic_block: quic.value ? '1' : '0', direct_bypass_kernel: bypassKernel.value ? '1' : '0',
    }
    await obxPut('/api/settings', body)
    ok.value = '已保存（网络相关项下次应用内核配置后生效）'
    await load()
  } catch (e) { err.value = e instanceof ObxApiError ? e.message : '保存失败' }
  finally { saving.value = false }
}

onMounted(load)
</script>
