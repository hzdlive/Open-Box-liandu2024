# 前置分流下拉溢出窗口修复报告

## 一、问题描述

用户截图：`修改前置自定义分流` 弹窗中，最后一行的 geosite 下拉框在搜索框输入 "x" 后，弹出的选项列表（0x0、1337x、dropbox...）被窗口底部截断，无法看到完整选项。

## 二、根因分析

### DOM 结构

```
modal-box max-w-4xl                    ← 弹窗（我们刚改的 4xl 档）
└── div.flex.max-h-96.overflow-y-auto  ← 规则列表滚动容器（line 244）
    └── div.flex.items-center.gap-2     ← 每一行规则
        └── button.input                ← 下拉触发按钮
        └── Teleport to="body"          ← 下拉菜单（已脱离滚动容器）
            └── div.fixed.z-[9999]      ← fixed 定位，:style="geoPos"
```

### 定位逻辑（SitesTab.vue:919-935）

```js
function toggleGeoDrop(ri, type, ev) {
  if (ev && ev.currentTarget) {
    const rect = ev.currentTarget.getBoundingClientRect()
    geoPos.value = {
      left: `${rect.left}px`,
      top: `${rect.bottom + 4}px`,  // ← 永远在按钮下方 4px
    }
  }
}
```

### 问题

1. **永远向下展开**：`top = rect.bottom + 4`，不考虑下方空间是否足够
2. **下拉高度**：`max-h-64` = 256px（含搜索框 + 选项列表）
3. **触发场景**：当按钮靠近视口底部时（如截图中最后一行），`rect.bottom + 256px > window.innerHeight`，下拉被视口截断

Teleport 到 body 已经正确避开了 `overflow-y-auto` 滚动容器的裁剪，问题纯粹是**视口边界**导致的。

## 三、修复方案

### 方案：智能上下展开

修改 `toggleGeoDrop`，计算上下空间，自动选择展开方向：

```js
function toggleGeoDrop(ri: number | string, type: string, ev?: Event) {
  const key = String(ri)
  if (geoOpen.value === key) {
    geoOpen.value = ''
  } else {
    geoOpen.value = key
    geoSearch.value = ''
    if (ev && ev.currentTarget) {
      const el = ev.currentTarget as HTMLElement
      const rect = el.getBoundingClientRect()
      const DROPDOWN_H = 256  // max-h-64
      const GAP = 4
      const spaceBelow = window.innerHeight - rect.bottom
      const spaceAbove = rect.top
      // 下方空间不足且上方空间更大时，向上展开
      if (spaceBelow < DROPDOWN_H + GAP && spaceAbove > spaceBelow) {
        geoPos.value = {
          left: `${rect.left}px`,
          top: `${rect.top - DROPDOWN_H - GAP}px`,
        }
      } else {
        geoPos.value = {
          left: `${rect.left}px`,
          top: `${rect.bottom + GAP}px`,
        }
      }
      // 防止左右溢出：下拉宽 w-96 (384px)
      const DROPDOWN_W = 384
      if (rect.left + DROPDOWN_W > window.innerWidth) {
        geoPos.value.left = `${Math.max(8, window.innerWidth - DROPDOWN_W - 8)}px`
      }
    }
  }
}
```

### 涉及位置

- `SitesTab.vue:919-935` 的 `toggleGeoDrop`（前置分流弹窗内的 geosite/geoip 下拉）
- `SitesTab.vue` 另一处 `toggleGeoDrop('f' + fri, ...)`（line 446，站点集规则的下拉）共用同一函数，一并修复

## 四、工作量

- 修改 1 个函数，约 20 行
- 无样式改动，无后端改动
- 需重新构建前端并部署

## 五、测试要点

1. 弹窗中最后一行下拉 → 应向上展开
2. 弹窗中第一行下拉 → 应向下展开（保持现有行为）
3. 窗口很窄时 → 下拉不应左右溢出
