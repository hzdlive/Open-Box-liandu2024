<template>
  <div>
    <ProxyGroup :name="name" />
    <!-- lane 区跟随卡片展开状态：收起时不显示（原生 CollapseCard 默认收起，
         点标题才展开；之前这里无条件渲染，收起时 lane 照样“掉”在卡片外面） -->
    <div v-if="isFailover && lanes.length && expanded" class="mt-2 ml-4 flex flex-col gap-2">
      <div
        v-for="lane in lanes"
        :key="lane.tag"
        class="rounded-box border border-base-300/30 bg-base-100 p-3"
      >
        <div class="flex items-center gap-2">
          <span class="text-sm font-semibold">{{ lane.displayName }}</span>
          <span class="text-xs opacity-60">({{ aliveCount(lane.members) }}/{{ lane.members.length }})</span>
          <span v-if="lane.active" class="badge badge-success badge-xs">当前</span>
        </div>
        <div class="mt-2 flex flex-wrap gap-1.5">
          <span
            v-for="m in lane.members"
            :key="m"
            class="badge badge-sm"
            :class="isAlive(m) ? 'badge-success' : 'badge-ghost'"
            :title="m"
          >{{ shortName(m) }}</span>
        </div>
      </div>
      <div class="flex items-center gap-2">
        <button class="btn btn-ghost btn-xs" :disabled="checking" @click="recheck" title="手动触发故障转移检测">
          {{ checking ? '检测中…' : '⚡ 检测' }}
        </button>
        <span v-if="lastResult" class="text-xs opacity-60">{{ lastResult }}</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import ProxyGroup from '@/components/proxies/ProxyGroup.vue'
import { proxyMap } from '@/assembly/proxies'
import { collapseGroupMap } from '@/store/settings'
import { obxGet, obxPost } from '../api'
import { isAlive, aliveCount, refreshAlive } from '../composables/useAliveCount'

const props = defineProps<{ name: string }>()

// 与原生 CollapseCard 共用同一展开状态：默认收起（map 默认空），点标题才展开
const expanded = computed(() => !!collapseGroupMap.value[props.name])

// 故障转移组判定：后端 /api/groups 中 type=failover
const failoverNames = ref<Set<string>>(new Set())
async function loadFailoverNames() {
  try {
    const data = await obxGet<any[]>('/api/groups')
    const list = Array.isArray(data) ? data : []
    failoverNames.value = new Set(
      list.filter((g: any) => g.type === 'failover').map((g: any) => g.name),
    )
  } catch {}
}
loadFailoverNames()

const isFailover = computed(() => failoverNames.value.has(props.name))

// lane 子组：从 proxyMap 中找 `{name}#*`
const lanes = computed(() => {
  const out: { tag: string; displayName: string; members: string[]; active: boolean }[] = []
  const group = proxyMap.value[props.name]
  const activeNow = group?.now || ''
  for (const [tag, info] of Object.entries(proxyMap.value)) {
    if (!tag.startsWith(props.name + '#')) continue
    const displayName = tag.slice(props.name.length + 1)
    out.push({
      tag,
      displayName,
      members: (info as any).all || [],
      active: activeNow === tag,
    })
  }
  return out
})

const checking = ref(false)
const lastResult = ref('')

async function recheck() {
  checking.value = true
  lastResult.value = ''
  try {
    const res = await obxPost<any>('/api/openbox/failover/recheck', { groupId: props.name })
    lastResult.value = res?.switched ? `已切换: ${res?.now || ''}` : '正常'
    await refreshAlive()
  } catch (e: any) {
    lastResult.value = '检测失败'
  } finally {
    checking.value = false
  }
}

function shortName(tag: string): string {
  return tag.length > 18 ? tag.slice(0, 17) + '…' : tag
}
</script>
