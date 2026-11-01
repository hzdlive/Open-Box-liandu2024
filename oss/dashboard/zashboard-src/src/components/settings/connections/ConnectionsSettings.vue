<template>
  <div class="text-sm">
    <template v-if="hasVisibleDisplayItems">
      <div class="settings-section-label">{{ $t('settingsSectionConnectionDisplay') }}</div>
      <div class="settings-grid">
        <SettingItem :setting-key="k.connectionStyle">
          <div class="setting-item-label">{{ $t('connectionStyle') }}</div>
          <!-- v0.1.366：PC、移动端两槽合并为一行，小屏自动换行 -->
          <div class="flex flex-wrap items-center gap-x-4 gap-y-2">
            <label class="flex items-center gap-1">
              <span class="text-xs opacity-70">PC</span>
              <SelectInput
                v-model="connectionDisplayStylePc"
                class="select select-sm min-w-24"
                :options="[
                  { value: CONNECTION_DISPLAY_STYLE.AUTO, label: $t('auto') },
                  { value: CONNECTION_DISPLAY_STYLE.CARD, label: $t('card') },
                  { value: CONNECTION_DISPLAY_STYLE.TABLE, label: $t('table') },
                ]"
              />
            </label>
            <label class="flex items-center gap-1">
              <span class="text-xs opacity-70">移动端</span>
              <SelectInput
                v-model="connectionDisplayStyleMobile"
                class="select select-sm min-w-24"
                :options="[
                  { value: CONNECTION_DISPLAY_STYLE.AUTO, label: $t('auto') },
                  { value: CONNECTION_DISPLAY_STYLE.CARD, label: $t('card') },
                  { value: CONNECTION_DISPLAY_STYLE.TABLE, label: $t('table') },
                ]"
              />
            </label>
          </div>
        </SettingItem>
        <SettingItem :setting-key="k.proxyChainDirection">
          <div class="setting-item-label">{{ $t('proxyChainDirection') }}</div>
          <SelectInput
            v-model="proxyChainDirection"
            class="select select-sm w-24"
            :options="
              Object.values(PROXY_CHAIN_DIRECTION).map((value) => ({
                value,
                label: $t(value),
              }))
            "
          />
        </SettingItem>
        <SettingItem
          :setting-key="k.tableWidthMode"
          :when="!isConnectionCard"
        >
          <div class="setting-item-label">{{ $t('tableWidthMode') }}</div>
          <SelectInput
            v-model="tableWidthMode"
            class="select select-sm min-w-24"
            :options="Object.values(TABLE_WIDTH_MODE).map((value) => ({ value, label: $t(value) }))"
          />
        </SettingItem>
        <SettingItem
          :setting-key="k.tableSize"
          :when="!isConnectionCard"
        >
          <div class="setting-item-label">{{ $t('tableSize') }}</div>
          <SelectInput
            v-model="tableSize"
            class="select select-sm min-w-24"
            :options="Object.values(TABLE_SIZE).map((value) => ({ value, label: $t(value) }))"
          />
        </SettingItem>
      </div>
    </template>

    <template v-if="hasVisibleIdentityItems">
      <div class="settings-section-label">{{ $t('settingsSectionClientIdentity') }}</div>
      <div class="settings-grid">
        <SettingItem
          :setting-key="k.resolveClientHostname"
          :when="can('dnsQuery')"
        >
          <div class="setting-item-label">{{ $t('resolveClientHostname') }}</div>
          <input
            v-model="resolveClientHostname"
            type="checkbox"
            class="toggle"
          />
        </SettingItem>
        <SourceIPLabels :setting-key="k.sourceIPLabels" />
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { can } from '@/assembly/backend'
import SelectInput from '@/components/common/SelectInput.vue'
import SourceIPLabels from '@/components/settings/connections/SourceIPLabels.vue'
import SettingItem from '@/components/settings/SettingItem.vue'
import { useIsSettingVisible } from '@/composables/settings'
import { CONNECTIONS_ITEM_KEYS } from '@/config/settingsItems'
import {
  CONNECTION_DISPLAY_STYLE,
  PROXY_CHAIN_DIRECTION,
  TABLE_SIZE,
  TABLE_WIDTH_MODE,
} from '@/constant'
import {
  connectionDisplayStyleMobile,
  connectionDisplayStylePc,
  isConnectionCard,
  proxyChainDirection,
  resolveClientHostname,
  tableSize,
  tableWidthMode,
} from '@/store/settings'
import { computed } from 'vue'

const k = CONNECTIONS_ITEM_KEYS
const isVisibleConnectionStyle = useIsSettingVisible(k.connectionStyle)
const isVisibleProxyChain = useIsSettingVisible(k.proxyChainDirection)
const isVisibleTableWidth = useIsSettingVisible(k.tableWidthMode)
const isVisibleTableSize = useIsSettingVisible(k.tableSize)
const isVisibleResolveHostname = useIsSettingVisible(k.resolveClientHostname)
const isVisibleSourceLabels = useIsSettingVisible(k.sourceIPLabels)

const hasVisibleDisplayItems = computed(
  () =>
    isVisibleConnectionStyle.value ||
    isVisibleProxyChain.value ||
    (!isConnectionCard.value && (isVisibleTableWidth.value || isVisibleTableSize.value)),
)
const hasVisibleIdentityItems = computed(
  () => (can('dnsQuery') && isVisibleResolveHostname.value) || isVisibleSourceLabels.value,
)
</script>
