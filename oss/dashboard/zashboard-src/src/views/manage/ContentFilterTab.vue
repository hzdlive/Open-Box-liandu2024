<template>
  <div class="space-y-4">
    <div class="flex items-center justify-between">
      <h2 class="text-lg font-bold">{{ $t('obx.contentFilter') }}</h2>
      <button class="btn btn-sm btn-primary" @click="loadFilters" :disabled="loading">
        {{ $t('obx.refresh') }}
      </button>
    </div>

    <p class="text-sm opacity-60">{{ $t('obx.contentFilterDesc') }}</p>

    <div v-if="loading" class="text-center py-8 opacity-60">{{ $t('obx.loading') }}</div>

    <div v-else class="space-y-3">
      <div
        v-for="f in filters"
        :key="f.id"
        class="card bg-base-100 shadow-sm border border-base-200"
      >
        <div class="card-body p-4">
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-3">
              <span class="text-2xl">{{ iconFor(f) }}</span>
              <div>
                <div class="font-bold">{{ f.name }}</div>
                <div class="text-xs opacity-60">{{ f.description }}</div>
              </div>
            </div>
            <label class="cursor-pointer flex items-center gap-2">
              <span class="text-xs opacity-60">{{ f.enabled ? $t('obx.enabled') : $t('obx.disabled') }}</span>
              <input
                type="checkbox"
                class="toggle toggle-primary toggle-sm"
                :checked="f.enabled"
                @change="toggleEnabled(f)"
              />
            </label>
          </div>

          <div class="mt-3 flex items-center gap-2 text-xs">
            <span class="opacity-60">{{ $t('obx.blockedDomains') }}:</span>
            <span class="badge badge-neutral">{{ domainCount(f) }}</span>
            <span v-if="f.snapshot_url" class="opacity-60 truncate max-w-xs" :title="f.snapshot_url">
              {{ f.snapshot_url }}
            </span>
            <button
              class="btn btn-xs btn-ghost ml-auto"
              @click="showDetail(f)"
            >
              {{ $t('obx.viewDetails') }}
            </button>
          </div>

          <div v-if="f.updated_at" class="mt-1 text-xs opacity-40">
            {{ $t('obx.updatedAt') }}: {{ formatTime(f.updated_at) }}
          </div>
        </div>
      </div>
    </div>

    <!-- 详情弹窗 -->
    <div v-if="detailFilter" class="modal modal-open">
      <div class="modal-box max-w-2xl">
        <h3 class="font-bold text-lg mb-2">{{ detailFilter.name }}</h3>
        <p class="text-sm opacity-60 mb-4">{{ detailFilter.description }}</p>

        <div class="mb-4">
          <label class="label text-sm">{{ $t('obx.snapshotUrl') }}</label>
          <div class="flex gap-2">
            <input
              v-model="editSnapshotUrl"
              class="input input-bordered input-sm flex-1"
              placeholder="https://..."
            />
            <button class="btn btn-sm btn-primary" @click="updateFromSnapshot" :disabled="updating">
              {{ updating ? $t('obx.updating') : $t('obx.updateFromSnapshot') }}
            </button>
          </div>
        </div>

        <div class="mb-2 flex items-center justify-between">
          <span class="text-sm font-bold">{{ $t('obx.blockedDomains') }} ({{ detailDomains.length }})</span>
          <input
            v-model="domainSearch"
            class="input input-bordered input-xs w-48"
            :placeholder="$t('obx.search')"
          />
        </div>
        <div class="max-h-64 overflow-y-auto bg-base-200 rounded p-2 text-xs font-mono">
          <div v-for="d in filteredDomains" :key="d" class="py-0.5">{{ d }}</div>
          <div v-if="!filteredDomains.length" class="opacity-40 text-center py-4">
            {{ $t('obx.noDomains') }}
          </div>
        </div>

        <div class="modal-action">
          <button class="btn btn-sm" @click="detailFilter = null">{{ $t('obx.close') }}</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { obxGet, obxPut } from '@/openbox/api'

const filters = ref<any[]>([])
const loading = ref(false)
const detailFilter = ref<any>(null)
const detailDomains = ref<string[]>([])
const domainSearch = ref('')
const editSnapshotUrl = ref('')
const updating = ref(false)

const iconFor = (f: any) => {
  if (f.name.includes('广告')) return '🚫'
  if (f.name.includes('跟踪')) return '👁️'
  if (f.name.includes('恶意')) return '⚠️'
  return '🛡️'
}

const domainCount = (f: any) => {
  const d = f.domains
  if (Array.isArray(d)) return d.length
  if (typeof d === 'string') {
    try { return JSON.parse(d).length } catch { return 0 }
  }
  return 0
}

const filteredDomains = computed(() => {
  if (!domainSearch.value) return detailDomains.value
  const q = domainSearch.value.toLowerCase()
  return detailDomains.value.filter(d => d.toLowerCase().includes(q))
})

const formatTime = (t: string) => {
  try { return new Date(t).toLocaleString() } catch { return t }
}

async function loadFilters() {
  loading.value = true
  try {
    filters.value = await obxGet<any[]>('/api/content-filters')
  } catch {
    filters.value = []
  } finally {
    loading.value = false
  }
}

async function toggleEnabled(f: any) {
  const newVal = !f.enabled
  try {
    await obxPut(`/api/content-filters/${f.id}`, { enabled: newVal })
    f.enabled = newVal
  } catch {}
}

function showDetail(f: any) {
  detailFilter.value = f
  editSnapshotUrl.value = f.snapshot_url || ''
  let domains: string[] = []
  if (Array.isArray(f.domains)) domains = f.domains
  else if (typeof f.domains === 'string') {
    try { domains = JSON.parse(f.domains) } catch { domains = [] }
  }
  detailDomains.value = domains
  domainSearch.value = ''
}

async function updateFromSnapshot() {
  if (!detailFilter.value || !editSnapshotUrl.value) return
  updating.value = true
  try {
    // 后端暂不支持从 URL 拉取，此处仅保存 URL
    // 实际拉取逻辑待后端实现
    await obxPut(`/api/content-filters/${detailFilter.value.id}`, {
      snapshot_url: editSnapshotUrl.value,
    })
    detailFilter.value.snapshot_url = editSnapshotUrl.value
    await loadFilters()
  } catch {} finally {
    updating.value = false
  }
}

onMounted(loadFilters)
</script>
