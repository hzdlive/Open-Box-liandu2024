# zashboard 原生功能复用分析报告

**日期**: 2026-10-20
**背景**: 用户指出 zashboard 面板本身已带节点显示、测速等功能，质疑为何重写，要求分析哪些可复用、避免重复造轮子。

## 1. 结论先行

| 页面 | 现状 | 结论 |
|------|------|------|
| 代理页 (`ObProxiesPage.vue`, 505 行) | 完全重写 | **约 60% 功能与 zashboard 原生重复**，应重构为"原生组件 + 定制扩展" |
| 连接/日志/规则/概览/设置页 | 直接复用原生 | ✅ 无问题 |
| 管理页 (`ManageView` + 10 个 Tab) | 全定制 | ✅ 合理，Open-Box 特有功能，zashboard 没有 |

**核心判断**: 当初 `31b1bb3` 提交以"1:1 对标原版"为由重写代理页，但原版 Open-Box 的代理页**本身就是 zashboard 原生页**（截图中的 urltest_out/GLOBAL 卡片、节点延迟徽章、测速进度正是原生 `ProxyGroup` 组件）。我们用 505 行重写了 zashboard 用 ~150 行容器 + 成熟组件已实现的功能。

## 2. zashboard 原生已有的功能（v3.22.0）

### 2.1 代理组卡片 (`ProxyGroup.vue`, 80 行)
- 可折叠卡片，组名 + 类型 + 节点数
- `ProxyPreview` 圆点预览（截图中的彩色圆点）
- 展开后 `ProxiesContent`/`ProxyNodeGrid` 节点网格
- 组头测速按钮（`proxyGroupLatencyTest`），右键也可触发
- 移动端自适应 (`ProxyGroupForMobile`)
- 滚动位置记忆、双列布局、文件夹分组

### 2.2 节点卡片 (`ProxyNodeCard.vue`, 135 行)
- 节点名、协议类型、延迟徽章（颜色分档）
- 点击选择节点 (`handlerProxySelect` → Clash API `/proxies/{group}` PUT)
- 单节点测速 (`proxyLatencyTest`)
- 图标映射 (`ProxyIcon`)

### 2.3 测速体系 (`assembly/proxies/clash.ts` + `singbox.ts`)
- `proxyLatencyTest(name)` — 单节点测速
- `proxyGroupLatencyTest(group)` — 整组测速
- `allProxiesLatencyTest()` — 全部测速（顶部⚡按钮，截图3的"7/13 测试完成"即此）
- 并发限制 (pLimit 5)、超时配置、失败通知、延迟历史写入
- Clash API 与 sing-box RPC 双后端自适应

### 2.4 顶部控制条 (`ProxiesCtrl.tsx`)
- 搜索框（支持 Regex）
- 全部测速按钮
- 排序、视图切换

## 3. 我们的重写与原生功能的对比

### 3.1 完全重复（应删除，用原生代替）

| 我们的实现 | 原生对应 | 说明 |
|------------|----------|------|
| 节点组卡片 UI（折叠/展开/圆点/延迟徽章） | `ProxyGroup` + `ProxyPreview` + `ProxyNodeCard` | 像素级重复，含深色模式、响应式 |
| `selectNode()` → POST `/api/openbox/clash-select` | `handlerProxySelect()` → 直接调 Clash API | 我们经后端转发，原生直连 9090（更快，少一次跳转） |
| `latencyClass()` 延迟颜色分档 | `LatencyTag.vue` | 原生已按阈值着色，且阈值可在设置页调 |
| `dotClass()` 圆点颜色 | `ProxyPreview` | 原生已实现 |
| 搜索过滤 `filteredNodes` | `ProxiesCtrl` 搜索 + `ProxyGroupFilter` | 原生支持多关键词 + Regex |
| 10 秒轮询刷新 | 原生 `fetchProxies()` + 按需刷新 | 我们的轮询更粗暴（全量重载三 tab） |

### 3.2 部分重复（应基于原生扩展，而非重写）

| 功能 | 原生缺失的部分 | 建议 |
|------|---------------|------|
| 隐藏 `flip-`/`obflip-`/`__fo:`/`sub-` 内部组 | 原生显示所有组 | 给 `renderProxiesPageItems` 加过滤器，而非重写整个页面 |
| 故障转移组 lane 归集显示 | 原生无 lane 概念 | 在原生 `ProxyGroup` 下加一个 `FailoverLanes` 扩展组件 |
| ⚡ 故障转移手动检测按钮 | 原生无 | 在组头加一个按钮（`ProxyGroupHeader` 的 slot 或包装组件） |
| 可用数统计（alive/total，经 `/api/health`） | 原生读 Clash API `history`（sing-box 无 `alive` 字段） | 这是**真正的 gap**，但应做成 composable 注入，而非重写页面 |

### 3.3 真正定制（保留，但应独立成页/组件）

| 功能 | 说明 | 建议位置 |
|------|------|----------|
| **策略 Tab**（站点集 → flip 选择器） | Open-Box 特有：站点集是我们的概念，zashboard 无 | 独立 `ObPolicyTab.vue`，或并入管理页目标分流 |
| **订阅 Tab**（订阅卡片 + 节点展开） | Open-Box 特有：zashboard 无订阅概念 | 独立 `ObSubscriptionTab.vue` |
| 图标映射 `mapIcon()`（站点集 emoji） | 我们的站点集图标体系 | 保留为工具函数 |

## 4. 为什么当初重写了？（复盘）

1. **`31b1bb3` 的误判**: 以"1:1 对标原版代理页"为由重写，但没识别出原版代理页就是 zashboard 原生页。截图对比可证：原版截图的卡片样式、圆点、延迟徽章与原生 `ProxyGroup` 完全一致。
2. **过滤需求放大化**: 为了隐藏 4 类内部组、加故障转移 lane，選擇了重写整页，而非在原生渲染管线加过滤器（`renderProxiesPageItems` 是 computed，可包装）。
3. **alive 统计的特殊性**: sing-box Clash API 不返回 `alive` 字段（见 2026-10-19 排查），我们用 `/api/health` 补齐。这个需求是真实的，但实现位置错了——应在数据层（composable）解决，不应在视图层重写。

## 5. 重构方案（待用户拍板）

### 方案 A（推荐）：原生页 + 扩展
- 路由改回原生 `ProxiesPage.vue`
- 新增 `src/openbox/composables/useProxyGroupFilter.ts`：过滤 `flip-`/`obflip-`/`__fo:`/`sub-`
- 新增 `src/openbox/components/FailoverGroupExt.vue`：故障转移组的 lane 子卡片 + ⚡ 检测按钮，通过 `ProxyGroup` 的 slot 或高阶组件注入
- 新增 `src/openbox/composables/useAliveCount.ts`：经 `/api/health` 的 alive 统计，覆盖原生延迟显示
- 策略/订阅 Tab 拆为独立组件，放在代理页顶部作为 zashboard `SegmentedControl` 的扩展 tab，或移入管理页

**工作量**: 约 300 行新代码，删除 505 行重写，净减少 ~200 行，且后续 zashboard 行为变更（如测速逻辑优化）自动继承。

### 方案 B（最小改动）：保留重写，仅抽取重复部分
- 保留 `ObProxiesPage.vue` 结构
- 节点卡片改用原生 `ProxyNodeCard`
- 测速改调原生 `proxyGroupLatencyTest`/`proxyLatencyTest`（删我们的轮询+手动实现）

**工作量**: 小，但保留 505 行维护负担，治标不治本。

### 不做的
- 管理页 10 个 Tab：Open-Box 特有，无原生对应，保留。
- 连接/日志/规则/概览页：已复用原生，不动。

## 6. 诚实说明

- 本报告基于代码静态分析，未在真机对比原生页与重写页的像素级差异。
- 原生 `ProxyGroup` 的 `handlerProxySelect` 直连 9090；我们的 `/api/openbox/clash-select` 经后端转发。若切回原生，需确认 9090 直连在用户浏览器环境可用（之前控制台 `ERR_CONNECTION_REFUSED` 是内核没起，非架构问题）。
- 故障转移 lane 的 tag 命名（`{组名}#{显示名}`）是我们的约定，原生页会将其显示为普通组，必须配过滤器。
