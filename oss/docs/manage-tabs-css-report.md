# 管理页 Tab CSS 不一致修复报告

## 一、各 Tab 当前布局结构

| Tab | 根元素 | 内容容器 | 弹窗宽度 |
|-----|--------|---------|---------|
| 订阅管理 SubsTab | `<div>`（无类） | 混合：分享区 `rounded-box border p-4`，列表 `flex flex-col gap-3` | max-w-3xl |
| 出站节点 GroupsTab | `<div>`（无类） | 列表 `flex flex-col gap-2`，无卡片容器 | max-w-3xl |
| 目标分流 SitesTab | `<div>`（无类） | 混合：入口绕过卡片 `rounded-box`，列表无容器 | 4种混用：默认/max-w-2xl/max-w-3xl/max-w-4xl |
| DNS DnsTab | `flex flex-col gap-3` | 统一 `rounded-box border border-base-300/30 bg-base-100 p-4` | 4个都是 `modal-box`（无宽度约束） |
| 终端分流 TerminalsTab | `<div>`（无类） | 列表 `flex flex-col gap-2` | max-w-2xl 和 max-w-lg 混用 |
| 链式代理 ChainsTab | `<div>`（无类） | 列表 `flex flex-col gap-2` | max-w-2xl 和 max-w-lg 混用 |
| 共享网络 ShareTab | `<div>`（无类） | 列表 `flex flex-col gap-2` | max-w-2xl |
| 面板设置 SettingsTab | `flex flex-col gap-3` | 统一 `rounded-box border border-base-300/30 bg-base-100 p-4` | `modal-box`（无约束） |
| 备份 BackupTab | `space-y-4` | daisyUI `card bg-base-100 shadow` | 无弹窗 |
| 内容过滤 ContentFilterTab | `space-y-4` | daisyUI `card bg-base-100 shadow-sm border` | max-w-2xl |

外层：ManageView.vue 为 `mx-auto max-w-6xl p-4`。

## 二、不一致问题清单

### 🔴 P0：根元素三种写法并存
- 6 个 tab 用裸 `<div>`（无间距控制，靠内层 `mb-3` 硬撑）
- 2 个 tab 用 `space-y-4`（ContentFilterTab、BackupTab）
- 2 个 tab 用 `flex flex-col gap-3`（DnsTab、SettingsTab）
- **影响**：tab 切换时内容区上下间距明显跳动

### 🔴 P0：内容容器两种设计体系混用
- **体系 A**（DnsTab、SettingsTab）：`rounded-box border border-base-300/30 bg-base-100 p-4` —— 扁平圆角容器
- **体系 B**（ContentFilterTab、BackupTab）：daisyUI `card bg-base-100 shadow` —— 带阴影的卡片
- **体系 C**（其余 6 个）：无统一容器，列表项裸奔
- **影响**：视觉风格割裂，BackupTab/ContentFilterTab 看起来像另一个应用

### 🟡 P1：弹窗宽度无规范
- SitesTab 一个文件内出现 4 种宽度（默认/max-w-2xl/max-w-3xl/max-w-4xl）
- DnsTab 的 4 个弹窗全部无宽度约束（daisyUI 默认 max-w-lg，在大屏上显得窄）
- TerminalsTab/ChainsTab 在 max-w-lg 和 max-w-2xl 之间摇摆

### 🟡 P1：内层 max-w 随意
- max-w-xs、max-w-md、max-w-lg、max-w-2xl、max-w-3xl、max-w-4xl、max-w-48 七种都出现
- 同一类表单在不同 tab 用不同宽度

### 🟢 P2：标题栏相对统一（好的方面）
- 8 个 tab 用 `mb-3 flex items-center justify-between` + `text-lg font-bold`，可保留为规范

## 三、修复建议

统一为 **体系 A**（DnsTab/SettingsTab 风格），理由：它是 10 个 tab 中视觉最接近 zashboard 主界面的（zashboard 大量使用 `bg-base-100` + 细边框，无重阴影）。

### 规范

1. **根元素**：全部统一为 `<div class="flex flex-col gap-3">`
   - 废弃裸 `<div>` 和 `space-y-4`（`space-y` 在动态增删子元素时有 margin 塌陷问题，`flex gap` 更可靠）

2. **内容区块容器**：统一为 `<div class="rounded-box border border-base-300/30 bg-base-100 p-4">`
   - ContentFilterTab、BackupTab 的 daisyUI `card shadow` 改为此样式
   - 列表页的列表外层包一层此容器

3. **弹窗宽度规范**（全局只允许三种）：
   - 简单表单（确认、单字段编辑）：`modal-box` 默认（max-w-lg）
   - 复杂表单（订阅/链/站点集编辑）：`modal-box max-w-2xl`
   - 表格/规则编辑器（前置分流规则列表）：`modal-box max-w-4xl`

4. **标题栏**：保留现有 `mb-3 flex items-center justify-between` + `text-lg font-bold`

### 关于外层 max-w-6xl

ManageView 的 `mx-auto max-w-6xl p-4` 与 zashboard 主页面（`flex flex-col gap-3 p-3` 全宽）不一致。
建议改为 `flex flex-col gap-3 p-3` 与 zashboard 完全统一，消除切换页面时的跳动感。

## 四、工作量

- 约 10 个文件，40-60 处 class 修改
- 纯 CSS 类名调整，不涉及逻辑
- 需重新构建前端并部署
