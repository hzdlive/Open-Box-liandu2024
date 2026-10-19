<!-- Open-Box 二开：目标分流（1:1 对标原版 v0.1.331） -->
<template>
  <div class="flex flex-col gap-3">
    <div class="mb-3 flex items-center justify-between">
      <h2 class="text-lg font-bold">{{ $t('obx.siteSets') }}</h2>
      <button
        class="btn btn-primary btn-sm btn-square"
        :title="$t('obx.addSiteSet')"
        @click="openAdd"
      >
        +
      </button>
    </div>

    <div
      v-if="err"
      class="alert alert-error mb-3"
    >
      <span>{{ err }}</span>
    </div>

    <!-- 入口绕过状态（对标原版：显示模式及原因） -->
    <div v-if="entryPlan" class="mb-3 rounded-box border border-base-300/30 bg-base-100 px-4 py-2 flex items-center gap-2 text-sm">
      <span class="opacity-60">{{ $t('obx.entryBypassStatus') }}:</span>
      <span class="badge" :class="entryPlan.mode === 'blacklist' ? 'badge-warning' : 'badge-info'">
        {{ entryPlan.mode === 'blacklist' ? $t('obx.entryBypassBlacklist') : $t('obx.entryBypassWhitelist') }}
      </span>
      <span class="opacity-60 text-xs">{{ entryPlan.reason }}</span>
    </div>

    <!-- 卡片列表（对标原版） -->
    <div class="flex flex-col gap-2">
      <!-- 前置自定义分流（固定顶部） -->
      <div
        class="flex items-center gap-3 rounded-box border border-base-300/30 bg-base-100 px-4 py-3"
        :class="{ 'opacity-60': !frontEnabled }"
        title="固定位置,不能拖动排序"
      >
        <span class="opacity-40">≡</span>
        <span class="text-xl">📌</span>
        <div class="min-w-0 flex-1">
          <div class="flex items-center gap-2">
            <span class="font-medium">{{ $t('obx.frontRules') }}</span>
            <span class="badge badge-ghost badge-xs">{{ $t('obx.frontBadge') }}</span>
          </div>
          <div class="truncate text-sm opacity-60">
            {{ frontSummary }}
          </div>
        </div>
        <div class="flex items-center gap-1">
          <button
            class="btn btn-ghost btn-square btn-sm"
            :class="frontEnabled ? 'text-success' : 'opacity-40'"
            @click="toggleFrontEnabled"
          >
            ⏻
          </button>
          <button
            class="btn btn-ghost btn-square btn-sm"
            @click="openFrontEdit"
          >
            ✎
          </button>
          <button
            class="btn btn-ghost btn-square btn-sm hover:text-error"
            @click="clearFront"
          >
            🗑
          </button>
        </div>
      </div>

      <!-- 站点集卡片（可拖拽） -->
      <div
        v-for="(s, si) in sites"
        :key="s.id"
        class="flex items-center gap-3 rounded-box border border-base-300/30 bg-base-100 px-4 py-3"
        :class="{ 'opacity-60': !s.enabled, 'ring-2 ring-primary': dragOver === si }"
        draggable="true"
        @dragstart="onDragStart(si)"
        @dragover.prevent="onDragOver(si)"
        @dragleave="dragOver = -1"
        @drop="onDrop(si)"
        @dragend="dragOver = -1"
      >
        <span
          class="cursor-move opacity-40"
          title="拖拽排序"
        >≡</span>
        <span
          v-if="s.icon"
          class="text-xl"
          :style="s.icon_scale ? `transform: scale(${1 + s.icon_scale * 0.1})` : ''"
        >{{ iconEmoji(s.icon) }}</span>
        <div class="min-w-0 flex-1">
          <div class="font-medium">{{ s.name }}</div>
          <div class="truncate text-sm opacity-60">
            {{ ruleSummary(s) }}
          </div>
        </div>
        <div class="flex items-center gap-1">
          <button
            class="btn btn-ghost btn-square btn-sm"
            :class="s.enabled ? 'text-success' : 'opacity-40'"
            @click="toggleSite(s)"
          >
            ⏻
          </button>
          <button
            class="btn btn-ghost btn-square btn-sm"
            @click="openEdit(s)"
          >
            ✎
          </button>
          <button
            class="btn btn-ghost btn-square btn-sm hover:text-error"
            @click="removeSite(s)"
          >
            🗑
          </button>
        </div>
      </div>

      <!-- 其他（系统兜底，固定底部） -->
      <div
        class="flex items-center gap-3 rounded-box border border-base-300/30 bg-base-100 px-4 py-3"
        title="固定位置,不能拖动排序"
      >
        <span class="opacity-40">≡</span>
        <span class="text-xl">🌍</span>
        <div class="min-w-0 flex-1">
          <div class="flex items-center gap-2">
            <span class="font-medium">{{ $t('obx.fallback') }}</span>
            <span class="badge badge-ghost badge-xs">{{ $t('obx.systemFallback') }}</span>
          </div>
          <div class="truncate text-sm opacity-60">
            {{ $t('obx.fallbackHint') }}
          </div>
        </div>
        <div class="flex items-center gap-1">
          <button
            class="btn btn-ghost btn-square btn-sm opacity-40"
            disabled
          >
            ⏻
          </button>
          <button
            class="btn btn-ghost btn-square btn-sm"
            @click="openFallbackEdit"
          >
            ✎
          </button>
          <button
            class="btn btn-ghost btn-square btn-sm opacity-40"
            disabled
          >
            🗑
          </button>
        </div>
      </div>
    </div>

    <!-- 添加/编辑站点集弹窗 -->
    <div
      v-if="dlg"
      class="modal modal-open"
    >
      <div class="modal-box max-w-2xl">
        <div class="mb-4 flex items-center justify-between">
          <h3 class="text-lg font-bold">
            {{ dlg.id ? $t('obx.editSiteSet') : $t('obx.addSiteSet') }}
          </h3>
          <button
            class="btn btn-ghost btn-sm btn-square"
            @click="dlg = null"
          >
            ✕
          </button>
        </div>

        <div class="grid grid-cols-3 items-end gap-3">
          <label class="form-control">
            <span class="label-text mb-1">{{ $t('obx.icon') }}</span>
            <select
              v-model="dlg.icon"
              class="select select-bordered w-full"
            >
              <option value="">{{ $t('obx.none') }}</option>
              <option
                v-for="ic in ICONS"
                :key="ic.value"
                :value="ic.value"
              >
                {{ ic.label }}
              </option>
            </select>
          </label>
          <div class="form-control">
            <span class="label-text mb-1">{{ $t('obx.iconScale') }}</span>
            <div class="join">
              <button
                class="btn btn-bordered join-item"
                @click="dlg.icon_scale = Math.max(-5, (dlg.icon_scale || 0) - 1)"
              >−</button>
              <span class="join-item flex w-10 items-center justify-center border border-base-300">{{ dlg.icon_scale || 0 }}</span>
              <button
                class="btn btn-bordered join-item"
                @click="dlg.icon_scale = Math.min(5, (dlg.icon_scale || 0) + 1)"
              >+</button>
              <button
                class="btn btn-ghost join-item"
                @click="dlg.icon_scale = 0"
              >{{ $t('obx.reset') }}</button>
            </div>
          </div>
          <label class="form-control">
            <span class="label-text mb-1">{{ $t('obx.siteSetName') }}</span>
            <input
              v-model="dlg.name"
              class="input input-bordered w-full"
              :placeholder="$t('obx.siteSetNamePh')"
            />
          </label>
        </div>

        <div class="mt-4">
          <div class="mb-2 flex items-center justify-between">
            <span class="label-text font-medium">{{ $t('obx.rules') }}</span>
            <div class="flex gap-2">
              <button
                class="btn btn-ghost btn-xs"
                @click="importRules"
              >
                {{ $t('obx.importRules') }}
              </button>
              <button
                class="btn btn-ghost btn-xs"
                @click="addRule"
              >
                + {{ $t('obx.addRule') }}
              </button>
            </div>
          </div>
          <div class="flex max-h-96 flex-col gap-2 overflow-y-auto">
            <div
              v-for="(r, ri) in dlg.rules"
              :key="ri"
              class="flex items-center gap-2"
              :class="{ 'ring-2 ring-primary': ruleDragOver === ri }"
              draggable="true"
              @dragstart="onRuleDragStart(ri)"
              @dragover.prevent="onRuleDragOver(ri)"
              @dragleave="ruleDragOver = -1"
              @drop="onRuleDrop(ri)"
              @dragend="ruleDragOver = -1"
            >
              <span class="cursor-move opacity-40">≡</span>
              <select
                v-model="r.type"
                class="select select-bordered select-sm w-32"
              >
                <option value="domain_suffix">{{ $t('obx.domainSuffix') }}</option>
                <option value="domain">{{ $t('obx.domainExact') }}</option>
                <option value="domain_keyword">{{ $t('obx.domainKeyword') }}</option>
                <option value="ip_cidr">{{ $t('obx.ipCidr') }}</option>
                <option value="geosite">{{ $t('obx.geosite') }}</option>
                <option value="geoip">{{ $t('obx.geoip') }}</option>
                <option value="ruleset_url">{{ $t('obx.rulesetUrl') }}</option>
              </select>
              <!-- geosite/geoip 可搜索下拉 -->
              <div
                v-if="r.type === 'geosite' || r.type === 'geoip'"
                class="relative flex-1"
              >
                <button
                  class="input input-bordered input-sm relative w-full pr-8 text-left"
                  type="button"
                  @click="toggleGeoDrop(ri, r.type, $event)"
                >
                  <span class="block truncate">{{ r.value ? geoDisplay(r.type, r.value) : "" }}</span>
                  <span class="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 opacity-60">▾</span>
                </button>
                <Teleport to="body">
                  <div
                    v-if="geoOpen === '' + ri"
                    class="fixed inset-0 z-[9998]"
                    @click="geoOpen = ''"
                  ></div>
                  <div
                    v-if="geoOpen === '' + ri"
                    class="fixed z-[9999] max-h-64 w-96 overflow-hidden rounded-box border border-base-300 bg-base-100 shadow-lg"
                    :style="geoPos"
                  >
                  <div class="flex items-center gap-1 border-b border-base-300 p-2">
                    <input
                      ref="geoSearchInput"
                      v-model="geoSearch"
                      class="input input-bordered input-sm flex-1"
                      :placeholder="$t('obx.geoSearchPh')"
                      @input="onGeoSearch"
                    />
                    <button
                      v-if="geoSearch"
                      class="btn btn-ghost btn-xs"
                      @click="geoSearch = ''"
                    >
                      ✕
                    </button>
                    <select
                      v-if="r.type === 'geoip'"
                      v-model="geoFilter"
                      class="select select-bordered select-sm w-20"
                    >
                      <option value="all">{{ $t('obx.all') }}</option>
                    </select>
                  </div>
                  <div class="max-h-48 overflow-y-auto">
                    <button
                      v-for="item in filteredGeoList(r.type)"
                      :key="item.code"
                      class="flex w-full flex-col items-start px-3 py-1.5 text-left hover:bg-base-200"
                      @click="selectGeoItem(r, item.code)"
                    >
                      <span class="text-sm font-medium">{{ item.code }}</span>
                      <span class="text-xs opacity-60">{{ item.desc }}</span>
                    </button>
                    </div>
                  </div>
                </Teleport>
              </div>
              <input
                v-else
                v-model="r.value"
                class="input input-bordered input-sm flex-1"
                :placeholder="rulePh(r.type)"
              />
              <button
                v-if="r.type === 'geosite' || r.type === 'geoip'"
                class="btn btn-ghost btn-xs"
                @click="showRuleDetail(r)"
              >
                {{ $t('obx.detail') }}
              </button>
              <input
                v-model="r.note"
                class="input input-bordered input-sm w-24"
                :placeholder="$t('obx.note')"
              />
              <button
                class="btn btn-ghost btn-sm text-error"
                @click="dlg.rules.splice(Number(ri), 1)"
              >
                🗑
              </button>
            </div>
            <div
              v-if="!dlg.rules.length"
              class="py-8 text-center text-sm opacity-60"
            >
              {{ $t('obx.noRules') }}
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
            class="btn btn-success"
            :disabled="dlgBusy"
            @click="save"
          >
            {{ $t('obx.save') }}
          </button>
        </div>
      </div>
    </div>

    <!-- 前置自定义分流编辑弹窗 -->
    <div
      v-if="frontDlg"
      class="modal modal-open"
    >
      <div class="modal-box max-w-4xl">
        <div class="mb-4 flex items-center justify-between">
          <h3 class="text-lg font-bold">{{ $t('obx.editFrontRules') }}</h3>
          <button
            class="btn btn-ghost btn-sm btn-square"
            @click="frontDlg = null"
          >
            ✕
          </button>
        </div>
        <p class="mb-3 text-xs opacity-60">{{ $t('obx.frontRulesDesc') }}</p>
        <div class="mb-2 flex justify-end gap-2">
          <button
            class="btn btn-ghost btn-xs"
            @click="importFrontRules"
          >
            {{ $t('obx.importRules') }}
          </button>
          <button
            class="btn btn-ghost btn-xs"
            @click="addFrontRule"
          >
            + {{ $t('obx.addRule') }}
          </button>
        </div>
        <div class="flex max-h-96 flex-col gap-2 overflow-y-auto">
          <div
            v-for="(r, fri) in frontDlg.rules"
            :key="fri"
            class="flex items-center gap-2"
            :class="{ 'ring-2 ring-primary': frontDragOver === fri }"
            draggable="true"
            @dragstart="onFrontDragStart(fri)"
            @dragover.prevent="onFrontDragOver(fri)"
            @dragleave="frontDragOver = -1"
            @drop="onFrontDrop(fri)"
            @dragend="frontDragOver = -1"
          >
            <span class="cursor-move opacity-40">≡</span>
            <select
              v-model="r.type"
              class="select select-bordered select-sm w-32"
            >
              <option value="domain_suffix">{{ $t('obx.domainSuffix') }}</option>
              <option value="domain">{{ $t('obx.domainExact') }}</option>
              <option value="domain_keyword">{{ $t('obx.domainKeyword') }}</option>
              <option value="ip_cidr">{{ $t('obx.ipCidr') }}</option>
              <option value="geosite">{{ $t('obx.geosite') }}</option>
              <option value="geoip">{{ $t('obx.geoip') }}</option>
              <option value="ruleset_url">{{ $t('obx.rulesetUrl') }}</option>
              <option value="port">{{ $t('obx.port') }}</option>
            </select>
            <!-- geosite/geoip 可搜索下拉（前置规则） -->
            <div
              v-if="r.type === 'geosite' || r.type === 'geoip'"
              class="relative flex-1"
            >
              <button
                class="input input-bordered input-sm relative w-full pr-8 text-left"
                type="button"
                @click="toggleGeoDrop('f' + fri, r.type, $event)"
              >
                <span class="block truncate">{{ r.value ? geoDisplay(r.type, r.value) : "" }}</span>
                <span class="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 opacity-60">▾</span>
              </button>
              <Teleport to="body">
                <div
                  v-if="geoOpen === 'f' + fri"
                  class="fixed inset-0 z-[9998]"
                  @click="geoOpen = ''"
                ></div>
                <div
                  v-if="geoOpen === 'f' + fri"
                  class="fixed z-[9999] max-h-64 w-96 overflow-hidden rounded-box border border-base-300 bg-base-100 shadow-lg"
                  :style="geoPos"
                >
                <div class="flex items-center gap-1 border-b border-base-300 p-2">
                  <input
                    ref="geoSearchInput"
                    v-model="geoSearch"
                    class="input input-bordered input-sm flex-1"
                    :placeholder="$t('obx.geoSearchPh')"
                  />
                  <button
                    v-if="geoSearch"
                    class="btn btn-ghost btn-xs"
                    @click="geoSearch = ''"
                  >
                    ✕
                  </button>
                </div>
                <div class="max-h-48 overflow-y-auto">
                  <button
                    v-for="item in filteredGeoList(r.type)"
                    :key="item.code"
                    class="flex w-full flex-col items-start px-3 py-1.5 text-left hover:bg-base-200"
                    @click="selectGeoItem(r, item.code)"
                  >
                    <span class="text-sm font-medium">{{ item.code }}</span>
                    <span class="text-xs opacity-60">{{ item.desc }}</span>
                  </button>
                </div>
              </div>
                </Teleport>
            </div>
            <input
              v-else
              v-model="r.value"
              class="input input-bordered input-sm flex-1"
            />
            <button
              v-if="r.type === 'geosite' || r.type === 'geoip'"
              class="btn btn-ghost btn-xs"
              @click="showRuleDetail(r)"
            >
              {{ $t('obx.detail') }}
            </button>
            <input
              v-model="r.note"
              class="input input-bordered input-sm w-24"
              :placeholder="$t('obx.note')"
            />
            <button
              type="button"
              class="input input-bordered input-sm relative w-32 pr-8 text-left"
              @click="openObSel(r)"
            >
              <span class="block truncate">{{ targetDisplay(r.target) }}</span>
              <span class="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 opacity-60">▾</span>
            </button>
            <button
              class="btn btn-ghost btn-sm text-error"
              @click="frontDlg.rules.splice(Number(fri), 1)"
            >
              🗑
            </button>
          </div>
        </div>
        <div class="modal-action">
          <button
            class="btn btn-ghost"
            @click="frontDlg = null"
          >
            {{ $t('obx.cancel') }}
          </button>
          <button
            class="btn btn-success"
            @click="saveFront"
          >
            {{ $t('obx.save') }}
          </button>
        </div>
      </div>
    </div>

    <!-- 兜底站点集编辑弹窗 -->
    <div
      v-if="fallbackDlg"
      class="modal modal-open"
    >
      <div class="modal-box">
        <div class="mb-4 flex items-center justify-between">
          <h3 class="text-lg font-bold">{{ $t('obx.editFallback') }}</h3>
          <button
            class="btn btn-ghost btn-sm btn-square"
            @click="fallbackDlg = null"
          >
            ✕
          </button>
        </div>
        <div class="grid grid-cols-3 items-end gap-3">
          <label class="form-control">
            <span class="label-text mb-1">{{ $t('obx.icon') }}</span>
            <select
              v-model="fallbackDlg.icon"
              class="select select-bordered w-full"
            >
              <option value="">{{ $t('obx.none') }}</option>
              <option
                v-for="ic in ICONS"
                :key="ic.value"
                :value="ic.value"
              >
                {{ ic.label }}
              </option>
            </select>
          </label>
          <div class="form-control">
            <span class="label-text mb-1">{{ $t('obx.iconScale') }}</span>
            <div class="join">
              <button
                class="btn btn-bordered join-item"
                @click="fallbackDlg.icon_scale--"
              >−</button>
              <span class="join-item flex w-10 items-center justify-center border border-base-300">{{ fallbackDlg.icon_scale || 0 }}</span>
              <button
                class="btn btn-bordered join-item"
                @click="fallbackDlg.icon_scale++"
              >+</button>
              <button
                class="btn btn-ghost join-item"
                @click="fallbackDlg.icon_scale = 0"
              >{{ $t('obx.reset') }}</button>
            </div>
          </div>
          <label class="form-control">
            <span class="label-text mb-1">{{ $t('obx.siteSetName') }}</span>
            <input
              v-model="fallbackDlg.name"
              class="input input-bordered w-full"
            />
          </label>
        </div>
        <p class="mt-3 text-sm opacity-60">{{ $t('obx.fallbackRenameHint') }}</p>
        <div class="modal-action">
          <button
            class="btn btn-ghost"
            @click="fallbackDlg = null"
          >
            {{ $t('obx.cancel') }}
          </button>
          <button
            class="btn btn-success"
            @click="saveFallback"
          >
            {{ $t('obx.save') }}
          </button>
        </div>
      </div>
    </div>

    <!-- 出口选择器（节点/节点组） -->
    <div
      v-if="obSel.show"
      class="modal modal-open"
    >
      <div class="modal-box max-w-lg">
        <div class="mb-3 flex items-center justify-between">
          <h3 class="text-lg font-bold">{{ $t('obx.selectOutbound') }}</h3>
          <button
            class="btn btn-ghost btn-sm btn-square"
            @click="obSel.show = false"
          >
            ✕
          </button>
        </div>
        <!-- 页签 -->
        <div class="mb-3 flex gap-2">
          <button
            type="button"
            class="btn btn-sm"
            :class="obSel.tab === 'nodes' ? 'btn-success' : 'btn-ghost'"
            @click="obSel.tab = 'nodes'; obSel.search = ''"
          >
            {{ $t('obx.nodes') }} ({{ obSel.nodes.length }})
          </button>
          <button
            type="button"
            class="btn btn-sm"
            :class="obSel.tab === 'groups' ? 'btn-success' : 'btn-ghost'"
            @click="obSel.tab = 'groups'; obSel.search = ''"
          >
            {{ $t('obx.nodeGroups') }} ({{ obSel.groups.length }})
          </button>
          <button
            type="button"
            class="btn btn-sm"
            :class="obSel.tab === 'subs' ? 'btn-success' : 'btn-ghost'"
            @click="obSel.tab = 'subs'; obSel.search = ''"
          >
            {{ $t('obx.subscriptions') }} ({{ obSel.subs.length }})
          </button>
          <div class="relative flex-1">
            <input
              v-model="obSel.search"
              class="input input-bordered input-sm w-full pr-8"
              :placeholder="$t('obx.search')"
            />
            <button
              v-if="obSel.search"
              class="btn btn-ghost btn-xs absolute right-1 top-1/2 -translate-y-1/2"
              @click="obSel.search = ''"
            >
              ✕
            </button>
          </div>
        </div>
        <!-- 节点列表 -->
        <div
          v-if="obSel.tab === 'nodes'"
          class="max-h-96 overflow-y-auto"
        >
          <div class="mb-1 px-2 text-xs opacity-60">{{ $t('obx.builtin') }}</div>
          <button
            type="button"
            class="flex w-full items-center justify-between px-3 py-2 text-left hover:bg-base-200"
            @click="selectOb('direct')"
          >
            <span>{{ $t('obx.direct') }}</span>
          </button>
          <button
            type="button"
            class="flex w-full items-center justify-between px-3 py-2 text-left hover:bg-base-200"
            @click="selectOb('reject')"
          >
            <span>{{ $t('obx.reject') }}</span>
          </button>
          <div class="mb-1 mt-2 px-2 text-xs opacity-60">{{ $t('obx.nodes') }}</div>
          <div
            v-if="obSel.loading"
            class="p-4 text-center opacity-60"
          >
            {{ $t('obx.loading') }}
          </div>
          <button
            v-for="n in filteredObNodes"
            :key="n.id || n.tag"
            type="button"
            class="flex w-full items-center justify-between px-3 py-2 text-left hover:bg-base-200"
            @click="selectOb(n.tag || n.name)"
          >
            <span class="truncate"><span v-if="n.sub_name" class="badge badge-ghost badge-xs mr-1">{{ n.sub_name }}</span>{{ n.name || n.tag }}</span>
            <span
              v-if="obLatency(n.tag || n.name)"
              class="text-sm"
              :class="Number(obLatency(n.tag || n.name)) < 300 ? 'text-success' : Number(obLatency(n.tag || n.name)) < 800 ? 'text-warning' : 'text-error'"
            >
              {{ obLatency(n.tag || n.name) }}
            </span>
          </button>
          <!-- 链式代理分组（对标原版） -->
          <div v-if="filteredObChains.length" class="mb-1 mt-2 px-2 text-xs opacity-60">
            {{ $t('obx.chains') || '链式代理' }}
          </div>
          <button
            v-for="c in filteredObChains"
            :key="c.id"
            type="button"
            class="flex w-full items-center justify-between px-3 py-2 text-left hover:bg-base-200"
            @click="selectOb(c.name)"
          >
            <span class="truncate">{{ c.name }}</span>
            <span
              v-if="obLatency(c.name)"
              class="text-sm"
              :class="Number(obLatency(c.name)) < 300 ? 'text-success' : Number(obLatency(c.name)) < 800 ? 'text-warning' : 'text-error'"
            >
              {{ obLatency(c.name) }}
            </span>
          </button>
        </div>
        <!-- 节点组列表 -->
        <div
          v-else-if="obSel.tab === 'groups'"
          class="max-h-96 overflow-y-auto"
        >
          <div
            v-if="obSel.loading"
            class="p-4 text-center opacity-60"
          >
            {{ $t('obx.loading') }}
          </div>
          <button
            v-for="g in filteredObGroups"
            :key="g.id"
            type="button"
            class="flex w-full items-center justify-between px-3 py-2 text-left hover:bg-base-200"
            @click="selectOb(g.name)"
          >
            <span class="truncate">{{ g.name }}</span>
          </button>
        </div>
        <!-- 订阅列表 -->
        <div
          v-else-if="obSel.tab === 'subs'"
          class="max-h-96 overflow-y-auto"
        >
          <div
            v-if="obSel.loading"
            class="p-4 text-center opacity-60"
          >
            {{ $t('obx.loading') }}
          </div>
          <button
            v-for="s in filteredObSubs"
            :key="s.id"
            type="button"
            class="flex w-full items-center justify-between px-3 py-2 text-left hover:bg-base-200"
            @click="selectOb('sub-' + s.id)"
          >
            <span class="truncate">{{ s.name }}</span>
            <span class="badge badge-ghost badge-xs">{{ s.node_count }}</span>
          </button>
        </div>
      </div>
    </div>

    <!-- 规则详情弹窗（geosite/geoip） -->
    <div
      v-if="detailDlg.show"
      class="modal modal-open"
    >
      <div class="modal-box max-w-2xl">
        <div class="mb-2 flex items-center justify-between">
          <h3 class="text-lg font-bold">{{ detailDlg.name }}</h3>
          <button
            class="btn btn-ghost btn-sm btn-square"
            @click="detailDlg.show = false"
          >
            ✕
          </button>
        </div>
        <p class="mb-3 text-sm opacity-70">{{ detailDlg.title }}</p>
        <div class="relative mb-2">
          <input
            v-model="detailDlg.search"
            class="input input-bordered w-full pr-8"
            :placeholder="$t('obx.detailSearchPh')"
          />
          <button
            v-if="detailDlg.search"
            class="btn btn-ghost btn-xs absolute right-2 top-1/2 -translate-y-1/2"
            @click="detailDlg.search = ''"
          >
            ✕
          </button>
        </div>
        <p class="mb-2 text-sm opacity-60">{{ $t('obx.totalItems', { n: detailDlg.total }) }}</p>
        <div class="max-h-96 overflow-y-auto rounded-box border border-base-300">
          <div
            v-if="detailDlg.loading"
            class="p-4 text-center opacity-60"
          >
            {{ $t('obx.loading') }}
          </div>
          <div
            v-else-if="filteredDetailItems.length === 0"
            class="p-4 text-center opacity-60"
          >
            {{ $t('obx.noData') }}
          </div>
          <div
            v-for="(it, idx) in filteredDetailItems"
            :key="idx"
            class="flex items-center gap-4 border-b border-base-200 px-4 py-2 last:border-0"
          >
            <span class="w-16 text-xs opacity-60">{{ it.type }}</span>
            <span class="font-mono text-sm">{{ it.value }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ObxApiError, obxDel, obxGet, obxPost, obxPut } from '@/openbox/api'
import { computed, nextTick, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { GEOSITE_CATEGORIES, GEOIP_COUNTRIES } from './geodata'

const { t } = useI18n()

const ICONS = [
  { value: 'misc:stopwatch', label: '⏱ 秒表' },
  { value: 'brand:openai-light', label: '🤖 AI' },
  { value: 'brand:youtube', label: '▶ Youtube' },
  { value: 'brand:tiktok', label: '🎵 TikTok' },
  { value: 'brand:netflix-mono', label: 'N Netflix' },
  { value: 'brand:github-mono', label: '🐙 Github' },
  { value: 'brand:google', label: 'G Google' },
  { value: 'brand:microsoft', label: '🪟 Microsoft' },
  { value: 'brand:apple-light', label: '🍎 Apple' },
  { value: 'misc:game-soft', label: '🎮 Games' },
  { value: 'globe:earth-americas', label: '🌎 地球·彩色(美洲)' },
  { value: 'misc:shield', label: '🛡 盾牌' },
  { value: 'dart', label: '🎯 靶心' },
  { value: 'globe', label: '🌍 地球' },
  { value: 'bolt', label: '⚡ 闪电' },
]
function iconEmoji(v: string) {
  const found = ICONS.find((i) => i.value === v)
  if (found) return found.label.split(' ')[0]
  return '📦'
}

type SiteSet = {
  id: number
  name: string
  action: string
  group: string
  enabled: boolean
  icon: string
  icon_scale: number
  rules: any
}

const sites = ref<SiteSet[]>([])
const err = ref('')
const entryPlan = ref<any>(null)

async function loadEntryPlan() {
  try {
    entryPlan.value = await obxGet('/api/openbox/entry-plan')
  } catch (e) {
    // 静默失败，不阻塞主界面
  }
}
const dlg = ref<any>(null)
const dlgErr = ref('')
const dlgBusy = ref(false)
const frontDlg = ref<any>(null)
const fallbackDlg = ref<any>(null)
const frontRules = ref<any[]>([])
const frontEnabled = ref(true)
const groupOptions = ref<string[]>([])

// 订阅 ID -> 名称映射（用于 target 显示，不依赖弹窗状态）
const subNameMap = ref<Record<number, string>>({})
// 出口选择器（节点/节点组/订阅三页签）
const obSel = ref({
  show: false,
  rule: null as any,
  tab: 'nodes' as 'nodes' | 'groups' | 'subs',
  search: '',
  nodes: [] as any[],
  groups: [] as any[],
  chains: [] as any[],
  subs: [] as any[],
  health: {} as Record<string, number>,
  loading: false,
})

// 拖拽
const dragFrom = ref(-1)
const dragOver = ref(-1)
const ruleDragFrom = ref<number | string>(-1)
const ruleDragOver = ref<number | string>(-1)
const frontDragFrom = ref<number>(-1)
const frontDragOver = ref<number>(-1)

function ruleSummary(s: SiteSet) {
  const r = s.rules || {}
  const parts: string[] = []
  const rs = r.rule_sets || r.rulesets || []
  if (rs.length) parts.push(`${t('obx.ruleSets')}: ${rs.join(', ')}`)
  const ds = r.domain_suffix || []
  if (ds.length) parts.push(`${t('obx.domainSuffix')}: ${ds.slice(0, 5).join(', ')}${ds.length > 5 ? '...' : ''}`)
  return parts.join(' | ') || '—'
}

const frontSummary = computed(() => {
  if (!frontRules.value.length) return t('obx.noFrontRules')
  return frontRules.value.slice(0, 3).map((r: any) => `${r.value} → ${targetDisplay(r.target)}`).join(' · ') + (frontRules.value.length > 3 ? '...' : '')
})

function rulePh(type: string) {
  return {
    domain_suffix: 'google.com', domain: 'www.google.com', domain_keyword: 'google',
    ip_cidr: '1.1.1.0/24', geosite: 'youtube', geoip: 'cn',
    ruleset_url: 'https://例子/rules.list · 支持 .list / .mrs / .srs',
    port: '80, 443',
  }[type] || ''
}

// geosite/geoip 可搜索下拉
const geoOpen = ref<string>('')
const geoSearch = ref('')
const geoFilter = ref('all')
const geoPos = ref({ left: '0px', top: '0px' })
const geoSearchInput = ref<HTMLInputElement | null>(null)
function toggleGeoDrop(ri: number | string, type: string, ev?: Event) {
  const key = String(ri)
  if (geoOpen.value === key) {
    geoOpen.value = ''
  } else {
    geoOpen.value = key
    geoSearch.value = ''
    // 计算下拉位置（Teleport 到 body，用 fixed 定位）
    // 智能上下展开：下方空间不足且上方更大时向上展开
    if (ev && ev.currentTarget) {
      const el = ev.currentTarget as HTMLElement
      const rect = el.getBoundingClientRect()
      const DROPDOWN_H = 256  // max-h-64
      const DROPDOWN_W = 384  // w-96
      const GAP = 4
      const spaceBelow = window.innerHeight - rect.bottom
      const spaceAbove = rect.top
      let top: number
      if (spaceBelow < DROPDOWN_H + GAP && spaceAbove > spaceBelow) {
        top = rect.top - DROPDOWN_H - GAP
      } else {
        top = rect.bottom + GAP
      }
      // 防止左右溢出
      let left = rect.left
      if (left + DROPDOWN_W > window.innerWidth) {
        left = Math.max(8, window.innerWidth - DROPDOWN_W - 8)
      }
      geoPos.value = {
        left: `${left}px`,
        top: `${Math.max(8, top)}px`,
      }
    }
    // 下拉打开后自动聚焦搜索框
    nextTick(() => {
      geoSearchInput.value?.focus()
    })
  }
}
function onGeoSearch() {
  // 搜索时保持下拉打开
}
function filteredGeoList(type: string) {
  const list = type === 'geosite' ? GEOSITE_CATEGORIES : GEOIP_COUNTRIES
  const q = geoSearch.value.trim().toLowerCase()
  if (!q) return list.slice(0, 100)
  return list.filter((item) =>
    item.code.toLowerCase().includes(q) || item.desc.toLowerCase().includes(q),
  ).slice(0, 100)
}
function selectGeoItem(r: any, code: string) {
  r.value = code
  geoOpen.value = ''
  geoSearch.value = ''
}
function geoDisplay(type: string, code: string) {
  const list = type === 'geosite' ? GEOSITE_CATEGORIES : GEOIP_COUNTRIES
  const item = list.find((x) => x.code === code)
  return item ? `${item.code} ${item.desc}` : code
}
// 规则详情弹窗
const detailDlg = ref({
  show: false,
  name: '',
  title: '',
  search: '',
  items: [] as { type: string; value: string }[],
  total: 0,
  loading: false,
})
function showRuleDetail(r: any) {
  const name = `${r.type}-${r.value.trim()}`
  const title = geoDisplay(r.type, r.value.trim())
  detailDlg.value = {
    show: true,
    name,
    title,
    search: '',
    items: [],
    total: 0,
    loading: true,
  }
  obxGet(`/api/geodata/detail/${name}`)
    .then((d: any) => {
      detailDlg.value.items = d.items || []
      detailDlg.value.total = d.total || 0
      detailDlg.value.loading = false
    })
    .catch(() => {
      detailDlg.value.loading = false
    })
}
const filteredDetailItems = computed(() => {
  const q = detailDlg.value.search.trim().toLowerCase()
  if (!q) return detailDlg.value.items
  return detailDlg.value.items.filter((it) =>
    it.value.toLowerCase().includes(q),
  )
})

// 站点集 CRUD
// 出口选择器
async function openObSel(rule: any) {
  obSel.value.rule = rule
  obSel.value.show = true
  obSel.value.search = ''
  obSel.value.tab = 'nodes'
  obSel.value.loading = true
  try {
    const [nodes, groups, chains, health, subs] = await Promise.all([
      obxGet<any[]>('/api/nodes'),
      obxGet<any[]>('/api/groups'),
      obxGet<any[]>('/api/chains').catch(() => []),
      obxGet<any[]>('/api/health').catch(() => []),
      obxGet<any[]>('/api/subscriptions').catch(() => []),
    ])
    obSel.value.nodes = nodes || []
    obSel.value.chains = chains || []
    // 订阅列表（带节点数）
    obSel.value.subs = (subs || []).map((s: any) => ({
      ...s,
      node_count: (nodes || []).filter((n: any) => n.sub_id === s.id).length,
    }))
    // 过滤掉直连/拒绝（原版节点组页签没有这两项，它们在节点页签的内置区）
    obSel.value.groups = (groups || []).filter(
      (g: any) => g.name !== 'direct' && g.name !== 'block' && g.tag !== 'direct' && g.tag !== 'block',
    )
    const hm: Record<string, number> = {}
    for (const h of (health || [])) {
      if (h.latency_ms != null) hm[h.tag] = h.latency_ms
    }
    obSel.value.health = hm
  } catch (e) {
    // 忽略加载错误
  } finally {
    obSel.value.loading = false
  }
}
function selectOb(value: string) {
  if (obSel.value.rule) {
    obSel.value.rule.target = value
  }
  obSel.value.show = false
}
// 显示目标名称（sub-{id} 显示为订阅名）
function targetDisplay(target: string): string {
  if (!target) return ''
  if (target.startsWith('sub-')) {
    const sid = parseInt(target.slice(4))
    return subNameMap.value[sid] || target
  }
  return target
}
const filteredObNodes = computed(() => {
  const q = obSel.value.search.trim().toLowerCase()
  let list = obSel.value.nodes
  if (q) list = list.filter((n: any) => (n.name || n.tag || '').toLowerCase().includes(q))
  return list
})
const filteredObGroups = computed(() => {
  const q = obSel.value.search.trim().toLowerCase()
  let list = obSel.value.groups
  if (q) list = list.filter((g: any) => (g.name || '').toLowerCase().includes(q))
  return list
})
const filteredObSubs = computed(() => {
  const q = obSel.value.search.trim().toLowerCase()
  let list = obSel.value.subs
  if (q) list = list.filter((s: any) => (s.name || '').toLowerCase().includes(q))
  return list
})
const filteredObChains = computed(() => {
  const q = obSel.value.search.trim().toLowerCase()
  let list = obSel.value.chains || []
  if (q) list = list.filter((c: any) => (c.name || '').toLowerCase().includes(q))
  return list
})
function obLatency(tag: string): string {
  const v = obSel.value.health[tag]
  return v != null ? String(v) : ''
}
async function load() {
  try {
    sites.value = await obxGet<SiteSet[]>('/api/sitesets')
    const groups = await obxGet<any[]>('/api/groups')
    groupOptions.value = groups.map((g: any) => g.name)
  } catch (e) {
    err.value = e instanceof ObxApiError ? e.message : '加载失败'
  }
}
async function loadFront() {
  try {
    const data = await obxGet<any[]>('/api/front-rules')
    // 后端字段 -> 前端字段：rtype->type, domain->value
    frontRules.value = (data || []).map((r: any) => ({
      ...r,
      type: r.rtype || r.type || 'domain_suffix',
      value: r.domain ?? r.value ?? '',
    }))
  } catch { frontRules.value = [] }
}

function rulesToList(rules: any): any[] {
  // dict -> list
  const out: any[] = []
  const r = rules || {}
  for (const v of (r.domains || [])) out.push({ type: 'domain', value: v, note: '' })
  for (const v of (r.domain_suffix || [])) out.push({ type: 'domain_suffix', value: v, note: '' })
  for (const v of (r.domain_keyword || [])) out.push({ type: 'domain_keyword', value: v, note: '' })
  for (const v of (r.ip_cidr || [])) out.push({ type: 'ip_cidr', value: v, note: '' })
  for (const v of (r.rule_sets || r.rulesets || [])) {
    const [kind, name] = v.split('-', 2)
    out.push({ type: kind === 'geosite' ? 'geosite' : 'geoip', value: name || v, note: '' })
  }
  for (const v of (r.ruleset_urls || [])) out.push({ type: 'ruleset_url', value: v, note: '' })
  for (const v of (r.ports || [])) out.push({ type: 'port', value: v, note: '' })
  return out
}
function listToRules(list: any[]): any {
  const out: any = { domains: [], domain_suffix: [], domain_keyword: [], ip_cidr: [], rule_sets: [] }
  for (const r of list) {
    if (!r.value?.trim()) continue
    if (r.type === 'domain') out.domains.push(r.value.trim())
    else if (r.type === 'domain_suffix') out.domain_suffix.push(r.value.trim())
    else if (r.type === 'domain_keyword') out.domain_keyword.push(r.value.trim())
    else if (r.type === 'ip_cidr') out.ip_cidr.push(r.value.trim())
    else if (r.type === 'geosite') out.rule_sets.push(`geosite-${r.value.trim()}`)
    else if (r.type === 'geoip') out.rule_sets.push(`geoip-${r.value.trim()}`)
    else if (r.type === 'ruleset_url') {
      if (!out.ruleset_urls) out.ruleset_urls = []
      out.ruleset_urls.push(r.value.trim())
    }
    else if (r.type === 'port') {
      if (!out.ports) out.ports = []
      out.ports.push(r.value.trim())
    }
  }
  return out
}

function openAdd() {
  dlgErr.value = ''
  dlg.value = { id: null, name: '', icon: '', icon_scale: 0, action: 'proxy', group: '所有-自动', rules: [] }
}
function openEdit(s: SiteSet) {
  dlgErr.value = ''
  dlg.value = { id: s.id, name: s.name, icon: s.icon || '', icon_scale: s.icon_scale || 0, action: s.action, group: s.group, rules: rulesToList(s.rules) }
}
function addRule() {
  dlg.value.rules.push({ type: 'domain_suffix', value: '', note: '' })
}
function importRules() {
  // TODO: 导入规则
}
async function save() {
  if (!dlg.value?.name.trim()) { dlgErr.value = t('obx.nameRequired'); return }
  dlgBusy.value = true
  try {
    const body = { name: dlg.value.name.trim(), icon: dlg.value.icon, icon_scale: dlg.value.icon_scale, action: dlg.value.action, group: dlg.value.group, rules: listToRules(dlg.value.rules) }
    if (dlg.value.id) await obxPut(`/api/sitesets/${dlg.value.id}`, body)
    else await obxPost('/api/sitesets', body)
    dlg.value = null
    await load()
  } catch (e) {
    dlgErr.value = e instanceof ObxApiError ? e.message : t('obx.saveFailed')
  } finally {
    dlgBusy.value = false
  }
}
async function toggleSite(s: SiteSet) {
  try { await obxPut(`/api/sitesets/${s.id}`, { enabled: !s.enabled }); await load() }
  catch (e) { err.value = e instanceof ObxApiError ? e.message : '操作失败' }
}
async function removeSite(s: SiteSet) {
  if (!confirm(t('obx.delSiteSetConfirm', { name: s.name }))) return
  try { await obxDel(`/api/sitesets/${s.id}`); await load() }
  catch (e) { err.value = e instanceof ObxApiError ? e.message : '删除失败' }
}

// 拖拽排序
function onDragStart(i: number) { dragFrom.value = i }
function onDragOver(i: number) { dragOver.value = i }
async function onDrop(i: number) {
  const from = dragFrom.value
  dragFrom.value = -1; dragOver.value = -1
  if (from < 0 || from === i) return
  const list = [...sites.value]
  const [moved] = list.splice(from, 1)
  list.splice(i, 0, moved)
  sites.value = list
  try { await obxPost('/api/sitesets/reorder', { ids: list.map((s) => s.id) }) }
  catch (e) { err.value = '排序失败'; await load() }
}
function onRuleDragStart(i: number | string) { ruleDragFrom.value = i }
function onRuleDragOver(i: number | string) { ruleDragOver.value = i }
function onRuleDrop(i: number | string) {
  const from = Number(ruleDragFrom.value)
  const to = Number(i)
  ruleDragFrom.value = -1; ruleDragOver.value = -1
  if (from < 0 || from === to || !dlg.value) return
  const list = [...dlg.value.rules]
  const [moved] = list.splice(from, 1)
  list.splice(to, 0, moved)
  dlg.value.rules = list
}
function onFrontDragStart(i: number) { frontDragFrom.value = i }
function onFrontDragOver(i: number) { frontDragOver.value = i }
function onFrontDrop(i: number) {
  const from = frontDragFrom.value
  const to = i
  frontDragFrom.value = -1; frontDragOver.value = -1
  if (from < 0 || from === to || !frontDlg.value) return
  const list = [...frontDlg.value.rules]
  const [moved] = list.splice(from, 1)
  list.splice(to, 0, moved)
  frontDlg.value.rules = list
}

// 前置规则
function openFrontEdit() {
  frontDlg.value = { rules: frontRules.value.map((r: any) => ({ ...r })) }
}
function addFrontRule() {
  frontDlg.value.rules.push({ type: 'geosite', value: '', note: '', target: groupOptions.value[0] || '' })
}
function importFrontRules() {
  // TODO
}
async function saveFront() {
  try {
    // 前端字段 -> 后端字段：type->rtype, value->domain
    const rules = frontDlg.value.rules.map((r: any) => ({
      ...r,
      rtype: r.type,
      domain: r.value,
    }))
    await obxPut('/api/front-rules', { rules })
    frontDlg.value = null
    await loadFront()
    // 保存后自动应用配置（路由规则变更需要重建配置+重启内核才能生效）
    try {
      await obxPost('/api/config/apply?mode=full', {})
    } catch (e) {
      err.value = '规则已保存，但配置应用失败，请手动应用配置'
    }
  } catch (e) { err.value = '保存失败' }
}
async function toggleFrontEnabled() {
  frontEnabled.value = !frontEnabled.value
  // TODO: 保存到后端
}
async function clearFront() {
  if (!confirm(t('obx.clearFrontConfirm'))) return
  frontRules.value = []
  // TODO: 保存到后端
}

// 兜底
function openFallbackEdit() {
  fallbackDlg.value = { name: '其他', icon: 'globe', icon_scale: 0 }
}
async function saveFallback() {
  // TODO: 保存到后端
  fallbackDlg.value = null
}

onMounted(() => {
  load(); loadFront(); loadEntryPlan()
  // 预加载订阅名称映射，供 targetDisplay 使用
  obxGet<any[]>('/api/subscriptions').then((subs: any[]) => {
    for (const s of subs || []) subNameMap.value[s.id] = s.name
  }).catch(() => {})
})
</script>
