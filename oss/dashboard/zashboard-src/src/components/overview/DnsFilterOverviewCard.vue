<template>
  <div class="base-container w-full p-4">
    <div class="flex items-center justify-between">
      <div class="text-base-content/60 text-xs font-semibold tracking-wider uppercase">
        {{ $t('dnsFilterOverviewCard') }}
      </div>
      <span
        v-if="data"
        class="badge"
        :class="data.enabled ? 'badge-success' : 'badge-ghost'"
      >
        {{ data.enabled ? $t('dnsFilterEnabled') : $t('dnsFilterDisabled') }}
      </span>
    </div>
    <div
      v-if="data"
      class="text-base-content/60 mt-2 text-xs"
    >
      {{ data.window === '24h' ? $t('dnsFilterScope24h') : $t('dnsFilterScopeAll') }}
    </div>
    <div
      v-if="loading"
      class="mt-4 text-sm opacity-60"
    >
      …
    </div>
    <div
      v-else-if="data"
      class="mt-4 flex flex-col gap-2"
    >
      <div class="flex gap-6">
        <div>
          <div class="text-2xl font-bold">
            {{ data.queries }}
          </div>
          <div class="text-xs opacity-60">
            {{ $t('dnsFilterQueries') }}
          </div>
        </div>
        <div>
          <div class="text-2xl font-bold">
            {{ data.blocked }}
          </div>
          <div class="text-xs opacity-60">
            {{ $t('dnsFilterBlocked') }}
          </div>
        </div>
      </div>
      <div class="bg-base-200/30 rounded-xl p-3">
        <div class="mb-2 text-xs font-semibold">
          {{ $t('dnsFilterTopBlocked') }}
        </div>
        <ul
          v-if="data.top_blocked.length"
          class="flex flex-col gap-1 text-sm"
        >
          <li
            v-for="row in data.top_blocked"
            :key="row.domain"
            class="flex justify-between gap-2"
          >
            <span class="truncate">{{ row.domain }}</span>
            <span class="opacity-60">{{ row.count }}</span>
          </li>
        </ul>
        <div
          v-else
          class="text-sm opacity-60"
        >
          {{ $t('dnsFilterNoBlocks') }}
        </div>
      </div>
      <div
        v-if="!data.enabled"
        class="text-xs opacity-60"
      >
        {{ $t('dnsFilterNotCollected') }}
      </div>
      <div
        v-if="data.note"
        class="text-xs opacity-60"
      >
        {{ data.note }}
      </div>
      <router-link
        :to="{ name: ROUTE_NAME.manage, query: { tab: 'dns' } }"
        class="link text-sm"
      >
        {{ $t('dnsFilterManage') }}
      </router-link>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ROUTE_NAME } from '@/constant'
import { obxGet } from '@/openbox/api'
import { onMounted, ref } from 'vue'

type Overview = {
  enabled: boolean
  compiled_domains: number
  applied_at: string
  queries: number
  blocked: number
  window: string
  top_blocked: { domain: string; count: number }[]
  collected: boolean
  note: string
}

const data = ref<Overview | null>(null)
const loading = ref(true)

onMounted(async () => {
  try {
    data.value = await obxGet<Overview>('/api/dns/filter/overview')
  } catch {
    data.value = null
  } finally {
    loading.value = false
  }
})
</script>
