<!-- Open-Box 二开：DNS 设置（由旧版自研 UI 移植核心项） -->
<template>
  <div>
    <div class="mb-3 flex items-center justify-between">
      <h2 class="text-lg font-bold">{{ $t('obx.dns') }}</h2>
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

    <div class="grid max-w-3xl grid-cols-1 gap-3 md:grid-cols-2">
      <label class="form-control">
        <span class="label-text mb-1">{{ $t('obx.dnsMode') }}</span>
        <select
          v-model="f.mode"
          class="select select-bordered w-full"
        >
          <option value="dnsmasq">dnsmasq</option>
          <option value="firewall">{{ $t('obx.dnsFirewall') }} (hijack)</option>
          <option value="off">{{ $t('obx.dnsOff') }}</option>
        </select>
      </label>
      <label class="form-control">
        <span class="label-text mb-1">{{ $t('obx.dnsRegion') }}</span>
        <select
          v-model="f.region"
          class="select select-bordered w-full"
        >
          <option value="auto">{{ $t('obx.autoDetect') }}</option>
          <option value="cn">{{ $t('obx.regionCn') }}</option>
          <option value="outside">{{ $t('obx.regionOutside') }}</option>
        </select>
      </label>
      <label class="form-control">
        <span class="label-text mb-1">{{ $t('obx.directDns') }}</span>
        <textarea
          v-model="f.direct_dns"
          class="textarea textarea-bordered w-full"
          rows="2"
          placeholder="223.5.5.5&#10;wan（跟随 WAN）"
        />
        <span class="label-text-alt opacity-60">{{ $t('obx.multiUpstreamHint') }}</span>
      </label>
      <label class="form-control">
        <span class="label-text mb-1">{{ $t('obx.proxyDns') }}</span>
        <textarea
          v-model="f.proxy_dns"
          class="textarea textarea-bordered w-full"
          rows="2"
          placeholder="tcp://1.1.1.1"
        />
        <span class="label-text-alt opacity-60">{{ $t('obx.multiUpstreamHint') }}</span>
      </label>
      <label class="flex cursor-pointer items-center gap-3 rounded-box border border-base-300/30 bg-base-100 p-3">
        <input
          v-model="f.fakeip"
          type="checkbox"
          class="toggle"
        />
        <span>
          <span class="block font-medium">{{ $t('obx.fakeIp') }}</span>
          <span class="text-sm opacity-60">{{ $t('obx.fakeIpHint') }}</span>
        </span>
      </label>
      <label class="flex cursor-pointer items-center gap-3 rounded-box border border-base-300/30 bg-base-100 p-3">
        <input
          v-model="f.split"
          type="checkbox"
          class="toggle"
        />
        <span>
          <span class="block font-medium">{{ $t('obx.dnsSplit') }}</span>
          <span class="text-sm opacity-60">{{ $t('obx.dnsSplitHint') }}</span>
        </span>
      </label>
    </div>

    <div class="mt-4 flex items-center gap-2">
      <button
        class="btn btn-ghost btn-sm"
        :disabled="testing"
        @click="testUpstream"
      >
        {{ $t('obx.testUpstream') }}
      </button>
      <span
        v-if="latText"
        class="text-sm opacity-70"
      >{{ latText }}</span>
    </div>

    <h3 class="mt-6 mb-2 text-lg font-bold">{{ $t('obx.dnsRewrite') }}</h3>
    <div class="overflow-x-auto rounded-box border border-base-300/30 bg-base-100">
      <table class="table">
        <thead>
          <tr>
            <th>{{ $t('obx.domain') }}</th>
            <th>{{ $t('obx.target') }}</th>
            <th class="text-right">{{ $t('obx.actions') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="r in rewrites"
            :key="r.id"
          >
            <td class="font-mono">{{ r.domain }}</td>
            <td class="font-mono">{{ r.target }}</td>
            <td>
              <input
                type="checkbox"
                class="toggle toggle-xs"
                :checked="!!r.enabled"
                @change="toggleRewrite(r)"
              />
            </td>
            <td class="text-right">
              <button
                class="btn btn-ghost btn-xs text-error"
                @click="delRewrite(r)"
              >{{ $t('obx.delete') }}</button>
            </td>
          </tr>
          <tr v-if="!rewrites.length">
            <td
              colspan="3"
              class="text-center opacity-60"
            >{{ $t('obx.noRewrite') }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <div class="mt-2 flex gap-2">
      <input
        v-model="nr.domain"
        class="input input-bordered input-sm"
        :placeholder="$t('obx.domain')"
      />
      <input
        v-model="nr.target"
        class="input input-bordered input-sm"
        :placeholder="$t('obx.target')"
      />
      <button
        class="btn btn-primary btn-sm"
        @click="addRewrite"
      >{{ $t('obx.add') }}</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ObxApiError, obxDel, obxGet, obxPost, obxPut } from '@/openbox/api'
import { onMounted, ref } from 'vue'

const f = ref({ mode: 'dnsmasq', region: 'auto', direct_dns: '', proxy_dns: '', fakeip: false, split: true })
const rewrites = ref<{ id: number; domain: string; target: string; enabled: number }[]>([])
const nr = ref({ domain: '', target: '' })
const err = ref('')
const ok = ref('')
const saving = ref(false)
const testing = ref(false)
const latText = ref('')

async function load() {
  err.value = ''
  try {
    const d = await obxGet<any>('/api/dns')
    const toLines = (s: string) => (s || '').split(',').map((x) => x.trim()).filter(Boolean).join('\n')
    f.value = { mode: d.mode, region: d.region, direct_dns: toLines(d.direct_dns), proxy_dns: toLines(d.proxy_dns), fakeip: !!d.fakeip, split: !!d.split }
    rewrites.value = d.rewrites || []
    const lat = d.upstream_latency || {}
    const parts = Object.entries(lat).map(([k, v]) => `${k}: ${v}ms`)
    latText.value = parts.join(' · ')
  } catch (e) { err.value = e instanceof ObxApiError ? e.message : '加载失败' }
}

async function save() {
  saving.value = true; err.value = ''; ok.value = ''
  try {
    const toCsv = (s: string) => (s || '').split('\n').map((x) => x.trim()).filter(Boolean).join(', ')
    await obxPut('/api/dns', { ...f.value, direct_dns: toCsv(f.value.direct_dns), proxy_dns: toCsv(f.value.proxy_dns) })
    ok.value = '已保存（下次应用内核配置后生效）'
    await load()
  } catch (e) { err.value = e instanceof ObxApiError ? e.message : '保存失败' }
  finally { saving.value = false }
}

async function testUpstream() {
  testing.value = true; err.value = ''
  try {
    const r = await obxPost<any>('/api/dns/upstream-test', {})
    const lat = r.latency || r.upstream_latency || {}
    latText.value = Object.entries(lat).map(([k, v]) => `${k}: ${v}ms`).join(' · ') || '完成'
  } catch (e) { err.value = e instanceof ObxApiError ? e.message : '测速失败' }
  finally { testing.value = false }
}

async function addRewrite() {
  if (!nr.value.domain.trim() || !nr.value.target.trim()) return
  try {
    await obxPost('/api/dns/rewrite', { domain: nr.value.domain.trim(), target: nr.value.target.trim() })
    nr.value = { domain: '', target: '' }
    await load()
  } catch (e) { err.value = e instanceof ObxApiError ? e.message : '添加失败' }
}
async function delRewrite(r: { id: number }) {
  try { await obxDel(`/api/dns/rewrite/${r.id}`); await load() }
  catch (e) { err.value = e instanceof ObxApiError ? e.message : '删除失败' }
}
async function toggleRewrite(r: { id: number; enabled: number }) {
  try { await obxPut(`/api/dns/rewrite/${r.id}`, { enabled: r.enabled ? 0 : 1 }); await load() }
  catch (e) { err.value = e instanceof ObxApiError ? e.message : '操作失败' }
}

onMounted(load)
</script>
