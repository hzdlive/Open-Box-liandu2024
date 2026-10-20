<!-- Open-Box 二开：链式代理（1:1 对标原版添加/编辑模态框） -->
<template>
  <div class="flex flex-col gap-3">
    <div class="mb-3 flex items-center justify-between">
      <h2 class="text-lg font-bold">{{ $t('obx.chains') }}</h2>
      <button
        class="btn btn-primary btn-sm"
        @click="openAdd()"
      >
        + {{ $t('obx.addChain') }}
      </button>
    </div>

    <div
      v-if="err"
      class="alert alert-error mb-3"
    >
      <span>{{ err }}</span>
    </div>

    <!-- 链式代理列表 -->
    <div class="flex flex-col gap-2">
      <div
        v-for="c in chains"
        :key="c.id"
        class="flex items-center gap-3 rounded-box border border-base-300/30 bg-base-100 p-3"
        :class="{ 'opacity-60': !c.enabled }"
      >
        <span class="cursor-move opacity-40">≡</span>
        <div class="flex-1">
          <div class="flex items-center gap-2">
            <span class="font-medium">{{ c.name }}</span>
            <span class="badge badge-ghost badge-sm">{{ $t('obx.via') }} {{ c.front }}</span>
          </div>
          <div class="text-xs opacity-60 font-mono">
            {{ c.exit_protocol }} · {{ c.server }}:{{ c.port }}
          </div>
          <div v-if="chainResults[c.id]" class="text-xs mt-1">
            <span v-if="chainResults[c.id].ok" class="text-success">
              {{ chainResults[c.id].latency_ms }}ms · {{ chainResults[c.id].exit_ip }} · {{ chainResults[c.id].country }}
            </span>
            <span v-else class="text-error">{{ chainResults[c.id].error }}</span>
          </div>
          <div v-else-if="testingId === c.id" class="text-xs mt-1 opacity-60">测速中…</div>
        </div>
        <button
          class="btn btn-ghost btn-sm btn-square"
          :class="c.enabled ? 'text-success' : 'opacity-40'"
          :title="c.enabled ? $t('obx.disable') : $t('obx.enable')"
          @click="toggleEnabled(c)"
        >
          ⏻
        </button>
        <button
          class="btn btn-ghost btn-sm btn-square"
          :title="$t('obx.speedTest')"
          @click="testSpeed(c)"
        >
          ⚡
        </button>
        <button
          class="btn btn-ghost btn-sm btn-square"
          :title="$t('obx.edit')"
          @click="openEdit(c)"
        >
          ✎
        </button>
        <button
          class="btn btn-ghost btn-sm btn-square text-error"
          :title="$t('obx.delete')"
          @click="remove(c)"
        >
          🗑
        </button>
      </div>
      <div
        v-if="!chains.length"
        class="rounded-box border border-base-300/30 bg-base-100 p-6 text-center opacity-60"
      >
        {{ $t('obx.noChains') }}
      </div>
    </div>

    <!-- 添加/编辑模态框 -->
    <div
      v-if="dlg"
      class="modal modal-open"
    >
      <div class="modal-box max-w-2xl">
        <div class="mb-4 flex items-center justify-between">
          <h3 class="text-lg font-bold">
            {{ dlg.id ? $t('obx.editChain') : $t('obx.addChain') }}
          </h3>
          <button
            class="btn btn-ghost btn-sm btn-square"
            @click="dlg = null"
          >
            ✕
          </button>
        </div>

        <!-- 名称 -->
        <div class="mb-4">
          <label class="mb-1 block text-sm font-medium">{{ $t('obx.name') }}</label>
          <input
            v-model="dlg.name"
            class="input input-bordered w-full"
            :placeholder="$t('obx.chainNamePh')"
          />
        </div>

        <!-- 节点 -->
        <div class="mb-4">
          <div class="mb-2 flex items-center justify-between">
            <label class="text-sm font-medium">{{ $t('obx.node') }}</label>
            <div class="flex gap-1 rounded-full bg-base-200 p-1">
              <button
                type="button"
                class="btn btn-xs rounded-full"
                :class="dlg.inputMode === 'link' ? 'btn-success' : 'btn-ghost'"
                @click="dlg.inputMode = 'link'"
              >
                {{ $t('obx.link') }}
              </button>
              <button
                type="button"
                class="btn btn-xs rounded-full"
                :class="dlg.inputMode === 'fields' ? 'btn-success' : 'btn-ghost'"
                @click="dlg.inputMode = 'fields'"
              >
                {{ $t('obx.fields') }}
              </button>
            </div>
          </div>

          <!-- 链接模式 -->
          <div v-if="dlg.inputMode === 'link'">
            <textarea
              v-model="dlg.link"
              class="textarea textarea-bordered w-full font-mono text-sm"
              rows="4"
              :placeholder="$t('obx.chainLinkPh')"
            ></textarea>
            <p class="mt-1 text-xs opacity-60">{{ $t('obx.chainLinkDesc') }}</p>
          </div>

          <!-- 字段模式 -->
          <div v-else>
            <div class="mb-2 flex gap-2">
              <select
                v-model="dlg.protocol"
                class="select select-bordered w-28"
              >
                <option value="http">HTTP</option>
                <option value="https">HTTPS</option>
                <option value="socks5">SOCKS5</option>
                <option value="shadowsocks">Shadowsocks</option>
                <option value="vmess">VMess</option>
                <option value="vless">VLESS</option>
                <option value="trojan">Trojan</option>
                <option value="tuic">TUIC</option>
                <option value="hysteria2">Hysteria2</option>
                <option value="anytls">AnyTLS</option>
              </select>
              <input
                v-model="dlg.server"
                class="input input-bordered flex-1"
                :placeholder="$t('obx.hostPh')"
              />
              <input
                v-model.number="dlg.port"
                type="number"
                min="1"
                max="65535"
                class="input input-bordered w-24"
                :placeholder="$t('obx.port')"
              />
            </div>
            <div class="flex gap-2">
              <input
                v-model="dlg.username"
                class="input input-bordered flex-1"
                :placeholder="$t('obx.username')"
              />
              <input
                v-model="dlg.password"
                type="password"
                class="input input-bordered flex-1"
                :placeholder="$t('obx.password')"
              />
            </div>
            <p class="mt-1 text-xs opacity-60">{{ $t('obx.chainFieldsDesc') }}</p>
          </div>
        </div>

        <!-- 上游 -->
        <div class="mb-4">
          <label class="mb-1 block text-sm font-medium">{{ $t('obx.upstream') }}</label>
          <button
            type="button"
            class="input input-bordered relative w-full pr-8 text-left"
            @click="openObSel()"
          >
            <span class="block truncate">{{ dlg.front || $t('obx.selectOutbound') }}</span>
            <span class="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 opacity-60">▾</span>
          </button>
          <p class="mt-1 text-xs opacity-60">{{ $t('obx.chainUpstreamDesc') }}</p>
        </div>

        <!-- 测速 -->
        <div class="mb-4 rounded-box bg-base-200/50 p-3">
          <button
            type="button"
            class="btn btn-ghost btn-sm mb-1"
            :disabled="testing"
            @click="testDlgSpeed()"
          >
            <span v-if="testing" class="loading loading-spinner loading-xs"></span>
            <span v-else>⚡</span>
            {{ $t('obx.speedTest') }}
            <span v-if="testResult" class="ml-2" :class="testResult.ok ? 'text-success' : 'text-error'">
              <template v-if="testResult.ok">
                {{ testResult.latency_ms }}ms · {{ testResult.exit_ip }} · {{ testResult.country }}
              </template>
              <template v-else>{{ testResult.error || $t('obx.failed') }}</template>
            </span>
          </button>
          <p class="text-xs opacity-60">{{ $t('obx.chainTestDesc') }}</p>
        </div>

        <div
          v-if="dlgErr"
          class="alert alert-error mb-3"
        >
          <span>{{ dlgErr }}</span>
        </div>

        <div class="modal-action">
          <button
            class="btn btn-ghost"
            @click="dlg = null"
          >
            {{ $t('obx.cancel') }}
          </button>
          <button
            class="btn btn-success"
            :disabled="dlgBusy"
            @click="save()"
          >
            {{ $t('obx.save') }}
          </button>
        </div>
      </div>
    </div>

    <!-- 上游选择器（共享组件，不含订阅/链式页签） -->
    <ObOutboundSelector v-model:show="selShow" :show-chains="false" @select="onSelPick" />
  </div>
</template>

<script setup lang="ts">
import { ObxApiError, obxDel, obxGet, obxPost, obxPut } from '@/openbox/api'
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import ObOutboundSelector from '@/openbox/components/ObOutboundSelector.vue'

const { t } = useI18n()

type Chain = {
  id: number; name: string; exit_protocol: string; server: string; port: number
  params: any; front: string; enabled: boolean
}

const chains = ref<Chain[]>([])
const err = ref('')
const dlg = ref<any>(null)
const dlgErr = ref('')
const dlgBusy = ref(false)
const testing = ref(false)
const testResult = ref<{ ok: boolean; latency_ms?: number | null; latency?: number | null; exit_ip?: string | null; country?: string | null; error?: string } | null>(null)

const selShow = ref(false)

async function load() {
  err.value = ''
  try { chains.value = await obxGet<Chain[]>('/api/chains') }
  catch (e) { err.value = e instanceof ObxApiError ? e.message : '加载失败' }
}

function openAdd() {
  dlgErr.value = ''
  testResult.value = null
  dlg.value = {
    id: null, name: '', inputMode: 'link', link: '',
    protocol: 'http', server: '', port: 8080, username: '', password: '',
    front: '',
  }
}

function openEdit(c: Chain) {
  dlgErr.value = ''
  testResult.value = null
  const p = c.params || {}
  // 如果有原始链接，用链接模式；否则用字段模式
  const hasLink = !!p.link
  dlg.value = {
    id: c.id, name: c.name,
    inputMode: hasLink ? 'link' : 'fields',
    link: p.link || '',
    protocol: c.exit_protocol || 'http',
    server: c.server || '', port: c.port || 8080,
    username: p.username || '', password: p.password || '',
    front: c.front || '',
  }
}

// 解析分享链接，提取协议/host/端口/认证
function parseLink(link: string): { protocol: string; server: string; port: number; username: string; password: string } | null {
  const s = link.trim()
  try {
    // socks5://user:pass@host:port, http://, https://, ss://, vless://, trojan://
    const m = s.match(/^([a-z0-9+.-]+):\/\/(?:([^:@/]+)(?::([^@/]*))?@)?([^:/]+)(?::(\d+))?/i)
    if (!m) {
      // 尝试 主机:端口:用户名:密码 格式
      const m2 = s.match(/^([^:]+):(\d+):([^:]+):(.+)$/)
      if (m2) {
        return { protocol: 'http', server: m2[1], port: parseInt(m2[2]), username: m2[3], password: m2[4] }
      }
      return null
    }
    let proto = m[1].toLowerCase()
    if (proto === 'socks5' || proto === 'socks') proto = 'socks5'
    else if (proto === 'https') proto = 'https'
    else proto = 'http' // ss/vless/trojan 等暂按 http 处理，由后端细化
    return {
      protocol: proto,
      server: m[4] || '',
      port: m[5] ? parseInt(m[5]) : (proto === 'https' ? 443 : 80),
      username: m[2] ? decodeURIComponent(m[2]) : '',
      password: m[3] ? decodeURIComponent(m[3]) : '',
    }
  } catch { return null }
}

async function save() {
  if (!dlg.value) return
  dlgErr.value = ''
  const d = dlg.value
  if (!d.name.trim()) { dlgErr.value = t('obx.chainNameRequired'); return }
  if (!d.front) { dlgErr.value = t('obx.chainUpstreamRequired'); return }

  let protocol = d.protocol, server = d.server.trim(), port = d.port
  let username = d.username, password = d.password, link = ''
  if (d.inputMode === 'link') {
    link = d.link.trim()
    if (!link) { dlgErr.value = t('obx.chainLinkRequired'); return }
    const parsed = parseLink(link)
    if (!parsed) { dlgErr.value = t('obx.chainLinkInvalid'); return }
    protocol = parsed.protocol; server = parsed.server; port = parsed.port
    username = parsed.username; password = parsed.password
  } else {
    if (!server) { dlgErr.value = t('obx.chainHostRequired'); return }
    if (!port || port < 1 || port > 65535) { dlgErr.value = t('obx.chainPortInvalid'); return }
  }

  dlgBusy.value = true
  try {
    const body = {
      name: d.name.trim(), exit_protocol: protocol, server, port,
      params: { username, password, link: d.inputMode === 'link' ? link : '' },
      front: d.front,
    }
    if (d.id) await obxPut(`/api/chains/${d.id}`, body)
    else await obxPost('/api/chains', body)
    dlg.value = null
    await load()
  } catch (e) {
    dlgErr.value = e instanceof ObxApiError ? e.message : t('obx.saveFailed')
  } finally {
    dlgBusy.value = false
  }
}

async function toggleEnabled(c: Chain) {
  try {
    await obxPut(`/api/chains/${c.id}`, { enabled: !c.enabled })
    await load()
  } catch (e) { err.value = e instanceof ObxApiError ? e.message : '保存失败' }
}

async function remove(c: Chain) {
  if (!confirm(t('obx.deleteConfirm'))) return
  try { await obxDel(`/api/chains/${c.id}`); await load() }
  catch (e) { err.value = e instanceof ObxApiError ? e.message : '删除失败' }
}

const testingId = ref<number | null>(null)
const chainResults = ref<Record<number, any>>({})

async function testSpeed(c: Chain) {
  if (!c.id) return
  testingId.value = c.id
  try {
    const r = await obxPost<any>(`/api/chains/${c.id}/speedtest`, {})
    chainResults.value[c.id] = r
    if (!r.ok) err.value = r.error || t('obx.testFailed')
  } catch (e) {
    err.value = e instanceof ObxApiError ? e.message : '测速失败'
  } finally {
    testingId.value = null
  }
}

async function testDlgSpeed() {
  if (!dlg.value?.server) return
  testing.value = true
  testResult.value = null
  try {
    const r = await obxPost<any>('/api/chains/speedtest', {
      name: dlg.value.name || 'test',
      exit_protocol: dlg.value.exit_protocol || 'socks',
      server: dlg.value.server,
      server_port: dlg.value.server_port,
      params: { username: dlg.value.username, password: dlg.value.password },
      front: dlg.value.front,
    })
    testResult.value = r
  } catch (e) {
    testResult.value = { ok: false, error: e instanceof ObxApiError ? e.message : '测速失败' }
  } finally {
    testing.value = false
  }
}

// 上游选择器
function openObSel() {
  selShow.value = true
}

function onSelPick(v: string) {
  if (dlg.value) dlg.value.front = v
}


onMounted(load)
</script>
