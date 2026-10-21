<!-- Open-Box 二开：内容过滤 - Surge/QuantumultX 规则集管理器（1:1 对标原版） -->
<template>
  <div class="flex flex-col gap-3">
    <div class="flex items-center justify-between">
      <h2 class="text-lg font-bold">{{ $t('obx.contentFilter') }}</h2>
      <div class="flex gap-2">
        <button class="btn btn-sm btn-primary" @click="showAdd = true">
          + {{ $t('obx.add') || '添加' }}
        </button>
        <button class="btn btn-sm btn-ghost" @click="restoreDefaults" :disabled="loading">
          {{ $t('obx.restoreDefaults') || '恢复默认' }}
        </button>
        <button class="btn btn-sm btn-ghost" @click="load" :disabled="loading">
          {{ $t('obx.refresh') }}
        </button>
      </div>
    </div>

    <p class="text-sm opacity-60">{{ $t('obx.cfDescription') || '管理规则与脚本快照。iOS 运行同步的副本离线。' }}</p>

    <div v-if="loading" class="text-center py-8 opacity-60">{{ $t('obx.loading') }}</div>

    <div v-else-if="!rulesets.length" class="text-center py-8 opacity-60">
      {{ $t('obx.cfEmpty') || '暂无规则集。添加文件或 HTTPS URL。' }}
    </div>

    <div v-else class="space-y-3">
      <div
        v-for="r in rulesets"
        :key="r.id"
        class="rounded-box border border-base-300/30 bg-base-100 p-4"
      >
        <div>
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-3">
              <span class="text-2xl">{{ r.dialect === 'surge' ? '🔷' : '🔶' }}</span>
              <div>
                <div class="font-bold">{{ r.name }}</div>
                <div class="text-xs opacity-60">
                  {{ r.dialect }} · {{ formatSize(r.text_len) }}
                  <span v-if="r.source_url" class="truncate max-w-xs inline-block align-bottom" :title="r.source_url">
                    · {{ r.source_url }}
                  </span>
                </div>
              </div>
            </div>
            <div class="flex items-center gap-2">
              <label class="cursor-pointer flex items-center gap-2">
                <input
                  type="checkbox"
                  class="toggle toggle-primary toggle-sm"
                  :checked="r.enabled"
                  @change="toggleEnabled(r)"
                />
              </label>
              <button class="btn btn-xs btn-ghost" @click="showDetail(r)">
                {{ $t('obx.viewDetails') }}
              </button>
              <button class="btn btn-xs btn-ghost text-error" @click="delRuleset(r)">
                {{ $t('obx.delete') }}
              </button>
            </div>
          </div>

          <div v-if="hasSkipped(r)" class="mt-2 flex gap-2 text-xs flex-wrap">
            <span v-if="r.skipped_scripts" class="badge badge-warning badge-sm">
              脚本跳过: {{ r.skipped_scripts }}
            </span>
            <span v-if="r.skipped_unsupported" class="badge badge-ghost badge-sm">
              不支持: {{ r.skipped_unsupported }}
            </span>
            <span v-if="r.skipped_routing" class="badge badge-ghost badge-sm">
              路由规则跳过: {{ r.skipped_routing }}
            </span>
            <span v-if="r.skipped_unrepresentable" class="badge badge-ghost badge-sm">
              无法表示: {{ r.skipped_unrepresentable }}
            </span>
          </div>
        </div>
      </div>
    </div>

    <div v-if="showAdd" class="modal modal-open">
      <div class="modal-box max-w-2xl">
        <h3 class="font-bold text-lg mb-4">{{ $t('obx.add') || '添加' }}规则集</h3>
        <div class="space-y-3">
          <label class="form-control">
            <span class="label-text">名称</span>
            <input v-model="form.name" class="input input-bordered" placeholder="如：综合省流" />
          </label>
          <label class="form-control">
            <span class="label-text">方言</span>
            <select v-model="form.dialect" class="select select-bordered">
              <option value="surge">Surge</option>
              <option value="quantumultx">QuantumultX</option>
            </select>
          </label>
          <div class="tabs tabs-boxed w-fit">
            <a class="tab" :class="{ 'tab-active': inputMode === 'text' }" @click="inputMode = 'text'">粘贴文本</a>
            <a class="tab" :class="{ 'tab-active': inputMode === 'url' }" @click="inputMode = 'url'">URL</a>
          </div>
          <label v-if="inputMode === 'text'" class="form-control">
            <span class="label-text">规则文本（最大 512 KiB）</span>
            <textarea v-model="form.text" class="textarea textarea-bordered h-48 font-mono text-xs" placeholder="[Rule]&#10;DOMAIN-SUFFIX, ads.example.com, REJECT"></textarea>
          </label>
          <label v-else class="form-control">
            <span class="label-text">HTTPS URL</span>
            <input v-model="form.source_url" class="input input-bordered" placeholder="https://..." />
          </label>
          <div v-if="addErr" class="text-error text-sm">{{ addErr }}</div>
        </div>
        <div class="modal-action">
          <button class="btn btn-ghost" @click="showAdd = false">{{ $t('obx.cancel') }}</button>
          <button class="btn btn-primary" :disabled="adding" @click="doAdd">
            {{ adding ? '...' : $t('obx.confirm') }}
          </button>
        </div>
      </div>
    </div>

    <div v-if="detail" class="modal modal-open">
      <div class="modal-box max-w-2xl">
        <h3 class="font-bold text-lg mb-2">{{ detail.name }}</h3>
        <div class="text-sm opacity-60 mb-4">
          {{ detail.dialect }} · {{ detail.rules?.length || 0 }} 条规则 · {{ detail.scripts?.length || 0 }} 个脚本
        </div>
        <div v-if="detail.rules?.length" class="max-h-96 overflow-auto">
          <table class="table table-xs">
            <thead>
              <tr><th>动作</th><th>模式</th><th>类型</th></tr>
            </thead>
            <tbody>
              <tr v-for="(r, i) in detail.rules.slice(0, 100)" :key="i">
                <td><span class="badge badge-sm" :class="r.action === 'reject' ? 'badge-error' : 'badge-ghost'">{{ r.action }}</span></td>
                <td class="font-mono text-xs break-all">{{ r.pattern }}</td>
                <td class="text-xs opacity-60">{{ r.type }}</td>
              </tr>
            </tbody>
          </table>
          <div v-if="detail.rules.length > 100" class="text-xs opacity-60 mt-2">
            仅显示前 100 条，共 {{ detail.rules.length }} 条
          </div>
        </div>
        <div class="modal-action">
          <button class="btn btn-ghost" @click="detail = null">{{ $t('obx.close') }}</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { obxGet, obxPost, obxDel, obxPatch } from '@/openbox/api'

const { t } = useI18n()

const rulesets = ref<any[]>([])
const loading = ref(false)
const showAdd = ref(false)
const adding = ref(false)
const addErr = ref('')
const detail = ref<any>(null)
const inputMode = ref<'text' | 'url'>('text')

const form = ref({
  name: '',
  dialect: 'surge',
  text: '',
  source_url: '',
})

async function load() {
  loading.value = true
  try {
    rulesets.value = await obxGet<any[]>('/api/openbox/content-filter')
  } catch (e: any) {
    console.error(e)
  } finally {
    loading.value = false
  }
}

async function restoreDefaults() {
  if (!confirm('恢复默认规则集？（仅重建原版 3 条默认，你自己加的规则集保留）')) return
  loading.value = true
  try {
    const r = await obxPost<any>('/api/openbox/content-filter/restore-defaults', {})
    if (r.failed?.length) {
      alert('部分默认规则集未能预置：' + r.failed.map((f: any) => `${f.name}（${f.reason}）`).join('；'))
    }
    await load()
  } catch (e: any) {
    alert(e.message || '恢复默认失败')
  } finally {
    loading.value = false
  }
}

function hasSkipped(r: any) {
  return r.skipped_scripts || r.skipped_unsupported || r.skipped_routing || r.skipped_unrepresentable
}

function formatSize(bytes: number) {
  if (!bytes) return '0 B'
  if (bytes < 1024) return bytes + ' B'
  return (bytes / 1024).toFixed(1) + ' KiB'
}

async function doAdd() {
  addErr.value = ''
  if (!form.value.name.trim()) {
    addErr.value = '请输入名称'
    return
  }
  adding.value = true
  try {
    const payload: any = {
      name: form.value.name.trim(),
      dialect: form.value.dialect,
    }
    if (inputMode.value === 'text') {
      payload.text = form.value.text
    } else {
      payload.source_url = form.value.source_url.trim()
    }
    await obxPost('/api/openbox/content-filter', payload)
    showAdd.value = false
    form.value = { name: '', dialect: 'surge', text: '', source_url: '' }
    load()
  } catch (e: any) {
    addErr.value = e.message || '添加失败'
  } finally {
    adding.value = false
  }
}

async function toggleEnabled(r: any) {
  try {
    await obxPatch(`/api/openbox/content-filter/${r.id}`, { enabled: !r.enabled })
    r.enabled = !r.enabled
  } catch (e: any) {
    console.error(e)
  }
}

async function delRuleset(r: any) {
  if (!confirm(`删除规则集 "${r.name}"？`)) return
  try {
    await obxDel(`/api/openbox/content-filter/${r.id}`)
    load()
  } catch (e: any) {
    console.error(e)
  }
}

async function showDetail(r: any) {
  try {
    const data = await obxGet<any>(`/api/openbox/content-filter/${r.id}`)
    try { data.rules = JSON.parse(data.rules || '[]') } catch { data.rules = [] }
    try { data.scripts = JSON.parse(data.scripts || '[]') } catch { data.scripts = [] }
    detail.value = data
  } catch (e: any) {
    console.error(e)
  }
}

onMounted(load)
</script>
