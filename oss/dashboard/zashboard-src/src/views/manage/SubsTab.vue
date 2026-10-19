<!-- Open-Box 二开：订阅管理（1:1 对标原版订阅弹窗：订阅/规则/节点三 tab） -->
<template>
  <div class="flex flex-col gap-3">
    <div class="mb-3 flex items-center justify-between">
      <h2 class="text-lg font-bold">{{ $t('obx.subscriptions') }}</h2>
      <button
        class="btn btn-primary btn-sm"
        @click="openAdd"
      >
        {{ $t('obx.addSubscription') }}
      </button>
    </div>

    <div
      v-if="err"
      class="alert alert-error mb-3"
    >
      <span>{{ err }}</span>
    </div>

    <!-- 订阅分享 -->
    <div class="rounded-box border border-base-300/30 bg-base-100 p-4">
      <div class="flex items-center justify-between">
        <button class="flex items-center gap-2 font-bold" @click="shareCollapsed = !shareCollapsed">
          <span>{{ shareCollapsed ? '▶' : '▼' }}</span>
          {{ $t('obx.subShare') }}
        </button>
        <button class="btn btn-success btn-sm btn-circle" @click="openShareAdd">+</button>
      </div>
      <p v-if="!shareCollapsed" class="mt-1 text-xs opacity-60">{{ $t('obx.subShareHint') }}</p>
      <div v-if="!shareCollapsed && shares.length" class="mt-2 flex flex-col gap-2">
        <div v-for="sh in shares" :key="sh.id" class="flex items-center gap-2 rounded-box border border-base-200 p-2">
          <span class="flex-1 truncate text-sm">{{ sh.name }}</span>
          <span class="max-w-xs truncate font-mono text-xs opacity-60">{{ shareUrl(sh.token) }}</span>
          <button class="btn btn-ghost btn-xs" @click="copyLink(sh)">{{ $t('obx.copy') }}</button>
          <button class="btn btn-ghost btn-xs text-error" @click="delShare(sh)">{{ $t('obx.delete') }}</button>
        </div>
      </div>
    </div>

    <!-- 订阅卡片 -->
    <div class="flex flex-col gap-3">
      <div
        v-for="(s, idx) in subs"
        :key="s.id"
        class="rounded-box border border-base-300/30 bg-base-100 p-4"
        :class="{ 'opacity-70': !s.enabled }"
        draggable="true"
        @dragstart="dragStart(idx)"
        @dragover.prevent
        @drop="dragDrop(idx)"
      >
        <!-- 卡片头（点击名称区域展开/折叠） -->
        <div class="mb-2 flex items-center gap-2">
          <span class="cursor-move opacity-40" @click.stop>≡</span>
          <button
            class="flex min-w-0 flex-1 items-center gap-2 text-left"
            @click="toggleExpand(s)"
          >
            <span class="text-sm opacity-60">{{ expandedSubs.has(s.id) ? '▾' : '▸' }}</span>
            <span class="truncate font-bold">{{ s.name }}</span>
            <span class="shrink-0 text-sm opacity-60">({{ s.node_count }}/{{ s.node_total }})</span>
          </button>
          <span v-if="!s.enabled" class="badge badge-ghost badge-sm">{{ $t('obx.disabled') }}</span>
          <div class="flex-1" />
          <button class="btn btn-ghost btn-sm btn-square" :class="s.enabled ? 'text-success' : 'opacity-40'" :title="$t('obx.enable')+'/'+$t('obx.disable')" @click="toggleEnabled(s)">⏻</button>
          <button class="btn btn-ghost btn-sm btn-square" :title="$t('obx.speedTest')" @click="speedTest(s)">⚡</button>
          <button class="btn btn-ghost btn-sm btn-square" :title="$t('obx.refresh')" :disabled="busyId === s.id" @click="refresh(s)">↻</button>
          <button class="btn btn-ghost btn-sm btn-square" :title="$t('obx.edit')" @click="openEdit(s)">✎</button>
          <button class="btn btn-ghost btn-sm btn-square text-error" :title="$t('obx.delete')" @click="remove(s)">🗑</button>
        </div>
        <!-- 更新信息 -->
        <div class="mb-2 flex items-center justify-between text-xs opacity-60">
          <span>{{ $t('obx.updatedAt') }} {{ fmtTime(s.updated_at) }}<span v-if="s.auto_update?.enabled"> · {{ $t('obx.autoUpdateEvery', { n: s.auto_update_hours || s.auto_update.days * 24 }) }}</span></span>
          <span v-if="s.traffic_used">{{ s.traffic_used }}</span>
        </div>
        <!-- 流量条 -->
        <div v-if="s.traffic_total" class="mb-2">
          <div class="h-1 w-full rounded-full bg-base-300">
            <div class="h-1 rounded-full bg-success" :style="{ width: s.traffic_percent + '%' }" />
          </div>
        </div>
        <!-- 节点状态点（折叠时显示） -->
        <div v-if="s.node_dots?.length && !expandedSubs.has(s.id)" class="flex flex-wrap gap-1">
          <span
            v-for="(d, i) in s.node_dots"
            :key="i"
            class="h-3 w-3 rounded-full"
            :class="d === 'g' ? 'bg-success' : d === 'y' ? 'bg-warning' : d === 'r' ? 'bg-error' : 'bg-base-300'"
            :title="d"
          />
        </div>
        <!-- 展开的节点网格 -->
        <div v-if="expandedSubs.has(s.id)" class="mt-2">
          <div v-if="expandingId === s.id" class="py-4 text-center text-sm opacity-60">
            {{ $t('obx.loading') }}
          </div>
          <div v-else-if="(subNodesCache[s.id] || []).length" class="grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5">
            <div
              v-for="n in subNodesCache[s.id]"
              :key="n.id || n.tag"
              class="rounded-box border border-base-300/30 bg-base-200/50 p-2"
            >
              <div class="truncate text-xs font-medium" :title="n.tag">{{ n.tag }}</div>
              <div class="mt-1 flex items-center justify-between">
                <span class="text-[10px] opacity-60">{{ n.protocol }}{{ n.params?.network ? ' / ' + n.params.network : '' }}</span>
                <span
                  v-if="subHealthCache[n.tag] != null"
                  class="badge badge-xs"
                  :class="Number(subHealthCache[n.tag]) < 300 ? 'badge-success' : Number(subHealthCache[n.tag]) < 800 ? 'badge-warning' : 'badge-error'"
                >{{ Math.round(Number(subHealthCache[n.tag])) }}</span>
                <span v-else class="badge badge-ghost badge-xs">-</span>
              </div>
            </div>
          </div>
          <div v-else class="py-4 text-center text-sm opacity-60">
            {{ $t('obx.noData') }}
          </div>
        </div>
        <div v-else-if="!s.enabled" class="text-xs opacity-60">
          {{ $t('obx.subDisabledHint') }}
        </div>
      </div>
      <div v-if="!subs.length && !loading" class="rounded-box border border-base-300/30 bg-base-100 p-6 text-center opacity-60">
        {{ $t('obx.noSubscriptions') }}
      </div>
    </div>

    <!-- 新增 / 编辑弹窗（三 tab：订阅 / 规则 / 节点） -->
    <div
      v-if="dlg"
      class="modal modal-open"
    >
      <div class="modal-box max-w-2xl">
        <div class="mb-4 flex items-center justify-between">
          <h3 class="text-lg font-bold">
            {{ dlg.id ? $t('obx.editSubscription') : $t('obx.addSubOrNode') }}
          </h3>
          <button
            class="btn btn-ghost btn-sm"
            @click="dlg = null"
          >✕</button>
        </div>

        <!-- tab 栏 -->
        <div class="mb-4 flex items-center justify-between">
          <div
            v-if="!dlg.id"
            class="tabs tabs-boxed tabs-sm"
          >
            <a
              class="tab"
              :class="{ 'tab-active': dlg.addMode === 'sub' }"
              @click="dlg.addMode = 'sub'"
            >{{ $t('obx.subscription') }}</a>
            <a
              class="tab"
              :class="{ 'tab-active': dlg.addMode === 'node' }"
              @click="dlg.addMode = 'node'"
            >{{ $t('obx.node') }}</a>
          </div>
          <div
            v-else
            class="w-24"
          />
          <div class="tabs tabs-boxed tabs-sm">
            <a
              class="tab"
              :class="{ 'tab-active': dlg.tab === 'sub' }"
              @click="dlg.tab = 'sub'"
            >{{ $t('obx.subscription') }}</a>
            <a
              class="tab"
              :class="{ 'tab-active': dlg.tab === 'rule' }"
              @click="dlg.tab = 'rule'"
            >{{ $t('obx.rule') }}</a>
            <a
              class="tab"
              :class="{ 'tab-active': dlg.tab === 'node' }"
              @click="openNodeTab"
            >{{ $t('obx.node') }}</a>
          </div>
        </div>

        <!-- tab: 订阅 -->
        <div v-if="dlg.tab === 'sub'">
          <label class="form-control mb-3">
            <span class="label-text mb-1">{{ $t('obx.name') }}</span>
            <input
              v-model="dlg.name"
              class="input input-bordered w-full"
              placeholder="比如“我的订阅”"
            />
          </label>

          <!-- 新建：订阅链接模式 -->
          <div v-if="!dlg.id && dlg.addMode === 'sub'">
            <div class="mb-1 flex items-center justify-between">
              <span class="label-text">{{ $t('obx.urls') }}</span>
              <button
                class="btn btn-ghost btn-xs"
                @click="dlg.urls.push('')"
              >＋ {{ $t('obx.addSubscription') }}</button>
            </div>
            <div
              v-for="(u, i) in dlg.urls"
              :key="i"
              class="mb-2 flex gap-2"
            >
              <input
                v-model="dlg.urls[i]"
                class="input input-bordered w-full"
                placeholder="https://"
              />
              <button
                class="btn btn-ghost btn-sm text-error"
                @click="dlg.urls.splice(i, 1)"
              >🗑</button>
            </div>
            <p class="mb-3 text-xs opacity-60">一行一个，多个地址的节点合在一起；支持内网 / 本机地址，不校验 https 证书。</p>
          </div>

          <!-- 新建：手动节点模式 -->
          <div v-if="!dlg.id && dlg.addMode === 'node'">
            <label class="form-control mb-3">
              <span class="label-text mb-1">{{ $t('obx.nodeContent') }}</span>
              <textarea
                v-model="dlg.nodeContent"
                class="textarea textarea-bordered w-full"
                rows="6"
                placeholder="粘贴 ss:// / trojan:// / hysteria2:// 等链接，或 Clash/sing-box 配置…"
                @input="debouncedPreview"
              ></textarea>
            </label>
            <p class="mb-3 text-xs opacity-60">一行一个节点链接（ss:// / trojan:// / vless:// / socks5:// 等），也支持整段 Clash / sing-box 配置。</p>
          </div>

          <!-- 编辑：订阅链接 -->
          <div v-if="dlg.id">
            <div class="mb-1 flex items-center justify-between">
              <span class="label-text">{{ $t('obx.urls') }}</span>
              <button
                class="btn btn-ghost btn-xs"
                @click="dlg.urls.push('')"
              >＋ {{ $t('obx.addSubscription') }}</button>
            </div>
            <div
              v-for="(u, i) in dlg.urls"
              :key="i"
              class="mb-2 flex gap-2"
            >
              <input
                v-model="dlg.urls[i]"
                class="input input-bordered w-full"
                placeholder="https://"
              />
              <button
                class="btn btn-ghost btn-sm text-error"
                @click="dlg.urls.splice(i, 1)"
              >🗑</button>
            </div>
            <p class="mb-3 text-xs opacity-60">一行一个，多个地址的节点合在一起；支持内网 / 本机地址，不校验 https 证书。</p>

            <div class="mb-3 rounded-box border border-base-300/30 p-3">
              <div class="mb-1 font-medium">{{ $t('obx.manualUpdate') }}</div>
              <p class="mb-2 text-xs opacity-60">{{ $t('obx.manualUpdateHint') }}</p>
              <textarea
                v-model="dlg.manualContent"
                class="textarea textarea-bordered w-full"
                rows="3"
                placeholder="粘贴 base64 订阅 / 链接列表 / Clash YAML"
              @input="debouncedPreview"></textarea>
              <button
                class="btn btn-ghost btn-sm mt-2"
                :disabled="!dlg.manualContent.trim() || dlgBusy"
                @click="doReimport"
              >{{ $t('obx.manualUpdate') }}</button>
            </div>
          </div>

          <div class="mb-3 flex flex-wrap items-center gap-4">
            <div class="rounded-box border border-base-300/30 p-3">
              <label class="flex cursor-pointer items-center gap-2">
                <input
                  v-model="dlg.auEnabled"
                  type="checkbox"
                  class="toggle toggle-sm"
                />
                <span class="label-text">{{ $t('obx.autoUpdate') }}</span>
              </label>
              <div
                v-if="dlg.auEnabled"
                class="mt-2 grid grid-cols-2 gap-2"
              >
                <label class="form-control">
                  <span class="label-text mb-1">{{ $t('obx.everyDays') }}</span>
                  <input
                    v-model.number="dlg.auDays"
                    type="number"
                    min="1"
                    class="input input-bordered input-sm w-full"
                  />
                </label>
                <label class="form-control">
                  <span class="label-text mb-1">{{ $t('obx.atHour') }}</span>
                  <input
                    v-model.number="dlg.auHour"
                    type="number"
                    min="0"
                    max="23"
                    class="input input-bordered input-sm w-full"
                  />
                </label>
              </div>
            </div>
            <label class="form-control">
              <span class="label-text mb-1">{{ $t('obx.dnsResolve') }}</span>
              <select
                v-model="dlg.dnsResolve"
                class="select select-bordered select-sm"
              >
                <option value="auto">{{ $t('obx.auto') }}</option>
                <option value="direct">{{ $t('obx.actDirect') }}</option>
                <option value="proxy">{{ $t('obx.actProxy') }}</option>
              </select>
            </label>
          </div>
        </div>

        <!-- tab: 规则 -->
        <div v-if="dlg.tab === 'rule'">
          <label class="mb-3 flex cursor-pointer items-center gap-2">
            <input
              v-model="dlg.rename.prefix"
              type="checkbox"
              class="checkbox checkbox-sm"
            />
            <span class="text-sm">节点名前加订阅名（如「{{ dlg.name || '机场名称' }} | 香港-01」）</span>
          </label>
          <div class="mb-3 flex items-center justify-between">
            <span class="font-bold">{{ $t('obx.renameRules') }}</span>
            <div class="flex items-center gap-2">
              <label class="flex cursor-pointer items-center gap-1">
                <input
                  v-model="dlg.rename.enabled"
                  type="checkbox"
                  class="toggle toggle-sm"
                />
              </label>
              <button
                class="btn btn-ghost btn-xs"
                @click="resetRename"
              >⟲ {{ $t('obx.reset') }}</button>
            </div>
          </div>
          <div class="mb-2 text-xs opacity-60">
            拖拽排序：
            <span
              v-for="(slot, i) in dlg.rename.order"
              :key="slot"
              class="badge badge-ghost badge-sm mr-1 gap-1"
            >
              {{ slotName(slot) }}
              <button
                class="opacity-60"
                :disabled="i === 0"
                @click="moveSlot(Number(i), -1)"
              >↑</button>
              <button
                class="opacity-60"
                :disabled="i === dlg.rename.order.length - 1"
                @click="moveSlot(Number(i), 1)"
              >↓</button>
            </span>
            <span class="ml-3">序号位数：<input
              v-model.number="dlg.rename.seq_digits"
              type="number"
              min="1"
              max="4"
              class="input input-bordered input-xs w-14"
            /></span>
          </div>
          <p class="mb-3 text-xs opacity-60">效果：{{ renamePreview }}</p>

          <div class="mb-2 flex items-center justify-between">
            <span class="font-medium">{{ $t('obx.regionKeywords') }}</span>
            <button
              class="btn btn-ghost btn-xs"
              @click="dlg.rename.regions.push({ flag: '', name: '', keywords: '' })"
            >＋ {{ $t('obx.add') }}</button>
          </div>
          <p class="mb-2 text-xs opacity-60">按原始节点名匹配（不区分大小写）。</p>
          <div
            v-for="(r, i) in dlg.rename.regions"
            :key="i"
            class="mb-1 flex items-center gap-2"
          >
            <span class="opacity-40">≡</span>
            <input
              v-model="r.flag"
              class="input input-bordered input-sm w-12"
              placeholder="旗"
            />
            <input
              v-model="r.name"
              class="input input-bordered input-sm w-20"
              placeholder="地区名"
            />
            <input
              v-model="r.keywords"
              class="input input-bordered input-sm flex-1"
              placeholder="关键词，逗号分隔"
            />
            <button
              class="btn btn-ghost btn-xs text-error"
              @click="dlg.rename.regions.splice(i, 1)"
            >✕</button>
          </div>

          <label class="form-control mb-2 mt-3">
            <span class="label-text mb-1">{{ $t('obx.unknownRegionTag') }}</span>
            <input
              v-model="dlg.rename.fallback"
              class="input input-bordered input-sm max-w-xs"
            />
          </label>
          <label class="form-control mb-2">
            <span class="label-text mb-1">{{ $t('obx.featureKeywords') }} <span class="opacity-60">命中的关键词转成大写拼进节点名</span></span>
            <input
              v-model="dlg.rename.features"
              class="input input-bordered input-sm w-full"
              placeholder="iepl,iplc,ipv6,专线,家宽,2x"
            />
          </label>
          <label class="form-control mb-2">
            <span class="label-text mb-1">{{ $t('obx.filterNodes') }} <span class="opacity-60">原始节点命名中夹关键词的整条不导入</span></span>
            <input
              v-model="dlg.rename.filter"
              class="input input-bordered input-sm w-full"
              placeholder="官网,工单,客服"
            />
          </label>
        </div>

        <!-- tab: 节点 -->
        <div v-if="dlg.tab === 'node'">
          <div v-if="!dlg.id">
            <div class="mb-2 flex items-center justify-between">
              <span class="text-sm">预览解析出 {{ previewNodes.length }} 个节点</span>
              <button class="btn btn-ghost btn-sm" :disabled="previewBusy" @click="doPreview">
                <span v-if="previewBusy" class="loading loading-spinner loading-xs"></span>
                {{ previewBusy ? '拉取中...' : '重新拉取' }}
              </button>
            </div>
            <p v-if="previewErr" class="mb-2 text-xs text-error">{{ previewErr }}</p>
            <div v-if="previewNodes.length" class="max-h-96 overflow-y-auto rounded-box border border-base-300/30">
              <div v-for="(n, i) in previewNodes" :key="i" class="flex items-center gap-2 border-b border-base-200 px-3 py-2 text-sm">
                <span class="flex-1 truncate">{{ n.name || n.tag }}</span>
                <span class="badge badge-ghost badge-xs">{{ n.protocol }}</span>
                <span class="font-mono text-xs opacity-60">{{ n.server }}:{{ n.port }}</span>
              </div>
            </div>
            <div v-else class="rounded-box border border-dashed border-base-300 p-8 text-center opacity-60">
              <div class="mb-2 text-2xl">🔍</div>
              填写链接或粘贴内容后，点"重新拉取"预览解析结果。
            </div>
          </div>
          <div v-else>
            <p class="mb-2">解析出 {{ subNodes.length }} 个节点 <span class="opacity-60">已应用重命名规则，可单独改名 / 禁用</span></p>
            <div class="mb-2 flex items-center gap-2">
              <div class="tabs tabs-boxed tabs-xs">
                <a
                  class="tab"
                  :class="{ 'tab-active': nodeTab === 'ok' }"
                  @click="nodeTab = 'ok'"
                >有效（{{ okNodes.length }}）</a>
                <a
                  class="tab"
                  :class="{ 'tab-active': nodeTab === 'off' }"
                  @click="nodeTab = 'off'"
                >禁用（{{ offNodes.length }}）</a>
              </div>
              <button
                class="btn btn-ghost btn-xs"
                @click="resetNames"
              >⟲ 恢复默认名称</button>
              <button
                class="btn btn-ghost btn-xs"
                :disabled="testingAll"
                @click="testAllNodes"
              >⚡ {{ testingAll ? '测速中…' : '一键测速' }}</button>
            </div>
            <div class="max-h-96 overflow-y-auto">
              <table class="table table-sm">
                <thead>
                  <tr>
                    <th>原名</th>
                    <th />
                    <th>新名</th>
                    <th>延迟</th>
                    <th class="text-right">操作</th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="n in shownNodes"
                    :key="n.id"
                  >
                    <td class="max-w-48 truncate opacity-60">{{ n.orig_tag || n.tag }}</td>
                    <td class="opacity-40">→</td>
                    <td><input
                      v-model="n._editTag"
                      class="input input-bordered input-xs w-full min-w-44"
                      @change="saveNodeTag(n)"
                    /></td>
                    <td class="text-xs opacity-60">{{ nodeLatency(n.tag) }}</td>
                    <td class="whitespace-nowrap text-right">
                      <button
                        class="btn btn-ghost btn-xs"
                        title="测速"
                        @click="testNode(n)"
                      >⚡</button>
                      <button
                        class="btn btn-ghost btn-xs"
                        :class="{ 'text-error': !n.disabled }"
                        :title="n.disabled ? '启用' : '禁用'"
                        @click="toggleNode(n)"
                      >{{ n.disabled ? '⏻' : '⊘' }}</button>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>

        <p
          v-if="dlgErr"
          class="mt-3 text-sm text-error"
        >
          {{ dlgErr }}
        </p>
        <div class="modal-action">
          <button
            class="btn btn-ghost"
            @click="dlg = null"
          >
            {{ $t('obx.cancel') }}
          </button>
          <button
            class="btn btn-primary"
            :disabled="dlgBusy"
            @click="save"
          >
            {{ $t('obx.save') }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ObxApiError, obxDel, obxGet, obxPost, obxPut } from '@/openbox/api'
import { computed, onMounted, ref } from 'vue'

type Sub = {
  id: number
  name: string
  urls: string[]
  node_count: number
  node_total: number
  enabled: boolean
  auto_update_hours: number
  auto_update: { enabled: boolean; days: number; hour: number }
  updated_at: string
  dns_resolve?: string
  rename?: any
  traffic_used?: string
  traffic_total?: string
  traffic_percent?: number
  node_dots?: string[]
}

const subs = ref<Sub[]>([])
const loading = ref(false)
const shareCollapsed = ref(true)
const previewNodes = ref<any[]>([])
// 展开状态：已展开的订阅 ID 集合
const expandedSubs = ref<Set<number>>(new Set())
// 订阅节点缓存：subId -> nodes
const subNodesCache = ref<Record<number, any[]>>({})
// 节点延迟缓存：tag -> latency_ms
const subHealthCache = ref<Record<string, number | null>>({})
const expandingId = ref<number | null>(null)
const previewBusy = ref(false)
const previewErr = ref('')
let previewTimer: any = null
function debouncedPreview() {
  if (previewTimer) clearTimeout(previewTimer)
  previewTimer = setTimeout(() => {
    doPreview()
  }, 800)
}
const dragIdx = ref(-1)
function dragStart(idx: number) {
  dragIdx.value = idx
}
async function dragDrop(idx: number) {
  if (dragIdx.value < 0 || dragIdx.value === idx) return
  const item = subs.value.splice(dragIdx.value, 1)[0]
  subs.value.splice(idx, 0, item)
  dragIdx.value = -1
  // 保存排序
  try {
    await obxPut('/api/openbox/subscriptions/order', { ids: subs.value.map((s) => s.id) })
  } catch (e) {
    err.value = e instanceof ObxApiError ? e.message : '保存排序失败'
  }
}
const err = ref('')
const busyId = ref<number | null>(null)
const dlg = ref<any>(null)
const dlgErr = ref('')
const dlgBusy = ref(false)

function fmtTime(t: string) {
  if (!t) return '—'
  return t.replace('T', ' ').slice(0, 19)
}

async function load() {
  loading.value = true
  err.value = ''
  try {
    subs.value = await obxGet<Sub[]>('/api/subscriptions')
  } catch (e) {
    err.value = e instanceof ObxApiError ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
}

// 1:1 对标原版预置地区（core/rename.py DEFAULT_REGIONS）
const DEFAULT_REGIONS = [
  { flag: '🇺🇸', name: '美国', keywords: 'us,united states,america,美国,美國,洛杉矶,硅谷,圣何塞,西雅图' },
  { flag: '🇭🇰', name: '香港', keywords: 'hk,hong kong,hongkong,香港,深港' },
  { flag: '🇯🇵', name: '日本', keywords: 'jp,japan,日本,东京,東京,大阪' },
  { flag: '🇸🇬', name: '新加坡', keywords: 'sg,singapore,新加坡,狮城,獅城' },
  { flag: '🇹🇼', name: '台湾', keywords: 'tw,taiwan,台湾,臺灣,台北,台中' },
  { flag: '🇰🇷', name: '韩国', keywords: 'kr,korea,韩国,韓國,首尔,首爾' },
  { flag: '🇬🇧', name: '英国', keywords: 'uk,gb,united kingdom,britain,英国,英國,伦敦,倫敦' },
  { flag: '🇩🇪', name: '德国', keywords: 'de,germany,德国,德國,法兰克福,法蘭克福' },
  { flag: '🇨🇳', name: '中国', keywords: 'cn,china,中国,中國,回国,回國,back to china' },
]
const DEFAULT_RENAME = () => ({
  enabled: false, prefix: true, order: ['region', 'feature', 'seq'], seq_digits: 2,
  regions: DEFAULT_REGIONS.map((r) => ({ ...r })),
  fallback: '其他', features: 'iepl,iplc,ipv6,专线,家宽,2x', filter: '官网,工单,客服',
})

function openAdd() {
  dlgErr.value = ''
  dlg.value = {
    id: null, tab: 'sub', addMode: 'sub', name: '', urls: [''], nodeContent: '',
    auEnabled: false, auDays: 1, auHour: 4, dnsResolve: 'auto', manualContent: '',
    rename: DEFAULT_RENAME(),
  }
}

async function openEdit(s: Sub) {
  dlgErr.value = ''
  const au = s.auto_update || { enabled: false, days: 1, hour: 4 }
  // fetch full detail (rename, dns_resolve)
  let detail: any = {}
  try { detail = await obxGet(`/api/subscriptions/${s.id}`) } catch { /* keep list data */ }
  const rn = detail.rename || s.rename || {}
  dlg.value = {
    id: s.id, tab: 'sub', addMode: 'sub', name: s.name,
    urls: [...(detail.urls || s.urls || [''])],
    nodeContent: '', auEnabled: !!au.enabled, auDays: au.days || 1, auHour: au.hour ?? 4,
    dnsResolve: detail.dns_resolve || s.dns_resolve || 'auto', manualContent: '',
    rename: {
      enabled: !!rn.enabled, prefix: rn.prefix !== false,
      order: [...(rn.order || ['region', 'feature', 'seq'])],
      seq_digits: rn.seq_digits || 2,
      regions: ((rn.regions && rn.regions.length ? rn.regions : DEFAULT_REGIONS).map((r: any) => ({ ...r }))),
      fallback: rn.fallback || '其他',
      features: rn.features || 'iepl,iplc,ipv6,专线,家宽,2x',
      filter: rn.filter || '官网,工单,客服',
    },
  }
  nodeTab.value = 'ok'
  subNodes.value = []
  health.value = []
}

function slotName(slot: string) {
  return { region: '地区', feature: '特征', seq: '序号' }[slot] || slot
}
function moveSlot(i: number, dir: number) {
  const o = dlg.value.rename.order
  const j = i + dir
  if (j < 0 || j >= o.length) return
  ;[o[i], o[j]] = [o[j], o[i]]
  updatePreview()
}
async function resetRename() {
  if (!confirm('重置为默认重命名规则吗？')) return
  try {
    const r = await obxPost<{ rename: any }>(`/api/subscriptions/${dlg.value.id}/reset-rename`, {})
    dlg.value.rename = { ...r.rename, regions: [...(r.rename.regions || [])] }
    updatePreview()
  } catch (e) { dlgErr.value = e instanceof ObxApiError ? e.message : '重置失败' }
}
const renamePreview = ref('')
async function updatePreview() {
  if (!dlg.value?.id) { renamePreview.value = ''; return }
  try {
    const r = await obxPost<{ preview: string }>(`/api/subscriptions/${dlg.value.id}/preview-rename`, { rename: dlg.value.rename })
    renamePreview.value = r.preview || ''
  } catch { renamePreview.value = '' }
}

async function save() {
  if (!dlg.value) return
  if (!dlg.value.name.trim()) { dlgErr.value = '名称不能为空'; return }
  dlgBusy.value = true
  dlgErr.value = ''
  try {
    const au = { enabled: dlg.value.auEnabled, days: dlg.value.auDays, hour: dlg.value.auHour }
    const rn = dlg.value.rename
    const rename = {
      enabled: rn.enabled, prefix: rn.prefix, order: rn.order, seq_digits: rn.seq_digits,
      regions: rn.regions, fallback: rn.fallback, features: rn.features, filter: rn.filter,
    }
    if (dlg.value.id) {
      const urls = dlg.value.urls.map((u: string) => u.trim()).filter(Boolean)
      await obxPut(`/api/subscriptions/${dlg.value.id}`, {
        name: dlg.value.name.trim(), urls, auto_update: au,
        dns_resolve: dlg.value.dnsResolve, rename,
      })
    } else if (dlg.value.addMode === 'sub') {
      const urls = dlg.value.urls.map((u: string) => u.trim()).filter(Boolean)
      if (!urls.length) { dlgErr.value = '订阅链接不能为空'; return }
      await obxPost('/api/subscriptions', {
        name: dlg.value.name.trim(), urls, auto_update: au,
        dns_resolve: dlg.value.dnsResolve, rename,
      })
    } else {
      if (!dlg.value.nodeContent.trim()) { dlgErr.value = '节点内容不能为空'; return }
      await obxPost('/api/nodes', {
        name: dlg.value.name.trim(), content: dlg.value.nodeContent.trim(),
      })
    }
    dlg.value = null
    await load()
  } catch (e) {
    dlgErr.value = e instanceof ObxApiError ? e.message : '保存失败'
  } finally {
    dlgBusy.value = false
  }
}

async function doReimport() {
  if (!dlg.value?.id || !dlg.value.manualContent.trim()) return
  dlgBusy.value = true
  dlgErr.value = ''
  try {
    await obxPost(`/api/subscriptions/${dlg.value.id}/reimport`, { content: dlg.value.manualContent })
    dlg.value.manualContent = ''
    await load()
    await openNodeTab()
  } catch (e) {
    dlgErr.value = e instanceof ObxApiError ? e.message : '导入失败'
  } finally {
    dlgBusy.value = false
  }
}

async function toggleEnabled(s: Sub) {
  try {
    await obxPut(`/api/subscriptions/${s.id}`, { enabled: !s.enabled })
    s.enabled = !s.enabled
  } catch (e) {
    err.value = e instanceof ObxApiError ? e.message : '操作失败'
  }
}

// 展开/折叠订阅卡片，加载节点和延迟
async function toggleExpand(s: Sub) {
  if (expandedSubs.value.has(s.id)) {
    expandedSubs.value.delete(s.id)
    expandedSubs.value = new Set(expandedSubs.value)
    return
  }
  expandedSubs.value.add(s.id)
  expandedSubs.value = new Set(expandedSubs.value)
  // 加载节点（缓存）
  if (!subNodesCache.value[s.id]) {
    expandingId.value = s.id
    try {
      const nodes = await obxGet<any[]>(`/api/subscriptions/${s.id}/nodes`)
      subNodesCache.value[s.id] = nodes || []
    } catch {
      subNodesCache.value[s.id] = []
    } finally {
      expandingId.value = null
    }
  }
  // 刷新延迟（每次展开都刷新）
  try {
    const health = await obxGet<any[]>('/api/health')
    for (const h of health || []) {
      if (h.tag) subHealthCache.value[h.tag] = h.latency_ms
    }
  } catch {}
}
async function speedTest(s: Sub) {
  busyId.value = s.id
  err.value = ''
  try {
    await obxPost(`/api/subscriptions/${s.id}/speedtest`, {})
    await load()
  } catch (e) {
    err.value = e instanceof ObxApiError ? e.message : '测速失败'
  } finally {
    busyId.value = null
  }
}

async function refresh(s: Sub) {
  busyId.value = s.id
  err.value = ''
  try {
    await obxPost(`/api/subscriptions/${s.id}/refresh`, {})
    await load()
  } catch (e) {
    err.value = e instanceof ObxApiError ? e.message : '刷新失败'
  } finally {
    busyId.value = null
  }
}

async function remove(s: Sub) {
  if (!confirm(`确定删除订阅「${s.name}」吗？其下节点将一并删除。`)) return
  try {
    await obxDel(`/api/subscriptions/${s.id}`)
    await load()
  } catch (e) {
    err.value = e instanceof ObxApiError ? e.message : '删除失败'
  }
}

// ---- 节点 tab ----
const nodeTab = ref<'ok' | 'off'>('ok')
const subNodes = ref<any[]>([])
const health = ref<any[]>([])
const testingAll = ref(false)
const okNodes = computed(() => subNodes.value.filter((n) => !n.disabled))
const offNodes = computed(() => subNodes.value.filter((n) => n.disabled))
const shownNodes = computed(() => nodeTab.value === 'ok' ? okNodes.value : offNodes.value)

async function doPreview() {
  if (!dlg.value) return
  const urls = (dlg.value.urls || []).filter((u: string) => u.trim())
  const content = (dlg.value.nodeContent || '').trim() + '\n' + (dlg.value.manualContent || '').trim()
  if (!urls.length && !content.trim()) {
    previewNodes.value = []
    return
  }
  previewBusy.value = true
  previewErr.value = ''
  try {
    const r = await obxPost<any>('/api/openbox/subscriptions/preview', {
      urls, content: content.trim(),
    })
    previewNodes.value = r.nodes || []
    if (r.errors?.length) {
      previewErr.value = r.errors.map((e: any) => `${e.url}: ${e.error}`).join('; ')
    }
  } catch (e) {
    previewErr.value = e instanceof ObxApiError ? e.message : '预览失败'
  } finally {
    previewBusy.value = false
  }
}

async function openNodeTab() {
  if (!dlg.value) return
  dlg.value.tab = 'node'
  if (!dlg.value.id) return
  try {
    const nodes = await obxGet<any[]>(`/api/subscriptions/${dlg.value.id}/nodes`)
    subNodes.value = nodes.map((n) => ({ ...n, _editTag: n.custom_tag || n.tag }))
    const h = await obxGet<any[]>('/api/health')
    health.value = h
  } catch (e) { dlgErr.value = e instanceof ObxApiError ? e.message : '加载节点失败' }
}
function nodeLatency(tag: string) {
  const h = health.value.find((x: any) => x.tag === tag)
  return h ? `${h.latency_ms ?? h.latency ?? ''}ms` : '—'
}
async function saveNodeTag(n: any) {
  try {
    await obxPut(`/api/nodes/${n.id}`, { custom_tag: n._editTag.trim() || null })
  } catch (e) { dlgErr.value = e instanceof ObxApiError ? e.message : '改名失败' }
}
async function toggleNode(n: any) {
  try {
    await obxPut(`/api/nodes/${n.id}`, { disabled: !n.disabled })
    n.disabled = !n.disabled
  } catch (e) { dlgErr.value = e instanceof ObxApiError ? e.message : '操作失败' }
}
async function testNode(n: any) {
  try {
    await obxPost('/api/health/check', { tag: n.tag })
    health.value = await obxGet<any[]>('/api/health')
  } catch (e) { dlgErr.value = e instanceof ObxApiError ? e.message : '测速失败' }
}
async function testAllNodes() {
  if (!dlg.value?.id) return
  testingAll.value = true
  try {
    await obxPost('/api/health/check', { sub_id: dlg.value.id })
    health.value = await obxGet<any[]>('/api/health')
  } catch (e) { dlgErr.value = e instanceof ObxApiError ? e.message : '测速失败' }
  finally { testingAll.value = false }
}
async function resetNames() {
  if (!confirm('恢复所有节点为重命名规则生成的默认名称？')) return
  try {
    await obxPost(`/api/subscriptions/${dlg.value.id}/reset-names`, {})
    await openNodeTab()
  } catch (e) { dlgErr.value = e instanceof ObxApiError ? e.message : '重置失败' }
}

// ---- 订阅分享 ----
type Share = { id: number; name: string; token: string; node_filter: string; created_at: string }
const shares = ref<Share[]>([])

function shareUrl(token: string) {
  return `${location.origin}/sub/${token}`
}
async function loadShares() {
  try { shares.value = await obxGet<Share[]>('/api/subscription-shares') }
  catch { shares.value = [] }
}
async function openShareAdd() {
  const name = prompt('分享名称：')
  if (!name?.trim()) return
  try {
    await obxPost('/api/subscription-shares', { name: name.trim() })
    await loadShares()
  } catch (e) { err.value = e instanceof ObxApiError ? e.message : '创建失败' }
}
async function copyLink(sh: Share) {
  try { await navigator.clipboard.writeText(shareUrl(sh.token)) }
  catch { /* clipboard unavailable */ }
}
async function delShare(sh: Share) {
  if (!confirm(`确定删除分享「${sh.name}」吗？`)) return
  try { await obxDel(`/api/subscription-shares/${sh.id}`); await loadShares() }
  catch (e) { err.value = e instanceof ObxApiError ? e.message : '删除失败' }
}

onMounted(() => { load(); loadShares() })
</script>
