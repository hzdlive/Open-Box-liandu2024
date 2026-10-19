# 代理页 CSS 不统一修复报告

## 一、问题概述

用户截图显示：代理页（ObProxiesPage）的卡片样式与 zashboard 原生的连接页、日志页明显不统一。

## 二、根本原因

### 2.1 技术栈割裂

| 页面 | 实现方式 | 样式体系 |
|------|---------|---------|
| 连接页 ConnectionsPage | zashboard 原生组件（ConnectionCardList/Table） | Tailwind + daisyUI（`bg-base-200`, `flex`, `gap-2`） |
| 日志页 LogsPage | zashboard 原生 | Tailwind + daisyUI |
| **代理页 ObProxiesPage** | **完全自研**（492行，`src/openbox/views/`） | **手写 CSS + CSS 变量**（`--ob-bg`, `--ob-border`） |

代理页是唯一一个**不用 Tailwind/daisyUI、而用 `<style scoped>` 手写 CSS** 的页面，导致：
- 颜色体系不同：手写 `#ffffff`/`#e5e7eb` vs daisyUI 的 `bg-base-100`/`border-base-300`（深色模式适配逻辑完全不同）
- 圆角/阴影/间距数值不同：`border-radius: 12px` vs daisyUI 的 `rounded-box`（1rem=16px）
- 字体大小/字重不同：手写 `14px/16px` vs daisyUI 的 `text-sm`/`font-semibold`

### 2.2 截图中的具体问题

从用户截图可见：

1. **卡片过宽、内容稀疏**：`.ob-card` 是 `flex-direction: column` 的全宽块，标题行只占左侧 1/3，右侧大片空白（延迟徽章孤零零在右上角）
2. **Tab 样式非 daisyUI**：`.ob-tab` 手写 `border-radius: 20px`，而 zashboard 其他页面的 tab 用 daisyUI `tabs tabs-boxed`
3. **搜索框样式不同**：`.ob-search input` 手写圆角 20px，与 zashboard 的 `input input-bordered` 不一致
4. **徽章颜色硬编码**：`.ob-card-badge` 写死 `#dcfce7`/`#16a34a`，深色模式下靠 CSS 变量覆盖，容易遗漏
5. **无障碍/交互缺失**：手写按钮无 `btn` 类的 focus/active 状态

### 2.3 深色模式风险

手写 CSS 用 `.dark .ob-card { --ob-bg: #1f2937; ... }` 覆盖变量，但：
- zashboard 的深色模式切换可能不是 `.dark` 类（daisyUI 用 `data-theme`）
- 若主题切换机制不同，代理页在深色模式下会显示异常

## 三、修复方案

### 方案 A（推荐）：重写为 Tailwind/daisyUI

将 ObProxiesPage.vue 的 `<style scoped>` 全部删除，改用 Tailwind/daisyUI 类：

```html
<!-- 改前 -->
<div class="ob-card">
  <div class="ob-card-head">
    <div class="ob-card-icon">{{ icon }}</div>
    ...

<!-- 改后 -->
<div class="rounded-box border border-base-300/30 bg-base-100 p-4">
  <div class="flex items-center gap-3 cursor-pointer">
    <div class="text-3xl">{{ icon }}</div>
    ...
```

具体映射表：

| 手写类 | daisyUI/Tailwind 等价 |
|--------|---------------------|
| `.ob-proxies { padding: 12px }` | `flex flex-col gap-3 p-3` |
| `.ob-tabs` | `tabs tabs-boxed mb-4 w-fit` |
| `.ob-tab` / `.active` | `tab` / `tab-active` |
| `.ob-search input` | `input input-bordered input-sm rounded-full w-70` |
| `.ob-cards { flex column gap-12px }` | `flex flex-col gap-3` |
| `.ob-card` | `rounded-box border border-base-300/30 bg-base-100 p-4` |
| `.ob-card-badge`（绿色） | `badge badge-success badge-sm` |
| `.ob-card-latency` | `badge badge-success`（按延迟变色：`badge-warning`/`badge-error`） |
| `.ob-option` | `rounded-box border p-3 cursor-pointer hover:border-success` |
| `.ob-option.selected` | `bg-success text-success-content border-success` |

**优点**：与 zashboard 完全统一，深色模式自动适配，无需维护两套颜色体系
**工作量**：约 492 行文件，重写 template 的 class + 删除 80 行 `<style>`，约 2-3 小时

### 方案 B（保守）：保留结构、只调数值

不改技术栈，只调整手写 CSS 的数值向 daisyUI 看齐：
- `border-radius: 12px` → `16px`（rounded-box）
- 卡片改双列布局，解决"右侧空白"问题
- Tab 改为 daisyUI 的 `tabs-boxed` 样式数值

**缺点**：治标不治本，深色模式仍有风险，下次改样式又要手写

## 四、建议

推荐**方案 A**。理由：
1. 用户明确要求"跟 zashboard 统一"，只有同技术栈才能真正统一
2. 代理页是用户高频使用的页面，值得一次性做对
3. 删除 80 行手写 CSS，减少长期维护负担

## 五、附：截图问题定位

- 卡片右侧空白 → `.ob-card-title { flex: 1 }` 把标题区撑满，但内容少 → 改为紧凑布局或双列
- Tab 胶囊感重 → `.ob-tab { border-radius: 20px }` 手写值与 daisyUI `tabs-boxed` 的圆角不同
- 整体"浮" → `box-shadow: 0 1px 3px` 与 zashboard 的扁平 `border` 风格不同
