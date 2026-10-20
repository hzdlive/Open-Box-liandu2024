# 代理页「策略设置」功能实现方案

> 原型：原版 Open-Box 代理页右上角 ⚙/✂ 按钮弹出的「策略设置」模态框（用户 2026-10-20 截图）。
> 结论先行：5 个功能中有 3 个 zashboard 原生机制已就绪（只缺 UI 入口），2 个需自研。

## 一、功能拆解

| # | 功能 | 原版行为 | 说明 |
|---|------|----------|------|
| 1 | 节点排序方式 | 下拉框，当前值"按延迟升序" | 控制策略组内节点卡片的排序 |
| 2 | 节点根据提供商分组 | 开关，当前开 | 组内节点按提供商（订阅）分段显示 |
| 3 | 节点卡片最小宽度 | 输入框 155 + 重置按钮 | 节点卡片 grid 的 minmax 宽度（px） |
| 4 | 显示顺序 | 13 个策略可拖动排序 | 只影响代理页「策略」Tab 的展示顺序，与流量命中无关 |
| 5 | 命中规则排序 | 只读：🚩前置自定义分流 + 13 策略编号 | 展示真实流量匹配顺序，改动入口在「设置 → 目标分流」 |

底部说明文案（原版原文，照搬）：
> 拖动调整 代理页的「策略」 按这个顺序显示，和命中顺序无关。
> 流量按这个顺序逐条匹配，首条命中生效；有域名的访问只看域名条件，都没命中就走兜底，IP 条件只管直接按 IP 发起的连接。要改去「设置 → 目标分流」。

## 二、复用评估（按用户"能复用就复用"原则）

| 功能 | zashboard 原生 | 结论 |
|------|---------------|------|
| 排序 | `PROXY_SORT_TYPE`（default/nameasc/namedesc/latencyasc/latencydesc）+ `proxySortType` store，`renderProxies.ts::sortProxies` 已接入 | **直接复用**，只做 UI 入口。原版下拉选项按此 5 项映射：默认排序/按名称升序/按名称降序/按延迟升序/按延迟降序 |
| 卡片宽度 | `minProxyCardWidth` store，`ProxyNodeGrid.vue` 已用 `minmax(min(${w}px,100%),1fr)` | **直接复用**，只做 UI 入口。默认值 155（与原版截图一致） |
| 提供商分组 | 原生 `ProxiesByProvider.vue` 按 Clash API 的 `provider-name` 分组 | **不能复用**：我们的 sing-box Clash API 出站是手建 outbounds，无 provider-name，全会掉进空分组。需自研：按我们 `/api/nodes` 的 `sub_name`（订阅名）分段 |
| 显示顺序 | 无 | **自研** |
| 命中排序 | 无（纯展示） | **自研**（只读派生数据） |

存储位置决策：zashboard 原生三项是 `useStorage`（浏览器 localStorage）。原版把它们放进面板级设置弹窗，意味着**服务端持久化**（换浏览器/清缓存不丢失，符合路由器面板预期）。方案：存服务端 settings，前端加载后同步写入 zashboard 的 store（`proxySortType.value = ...` 等），单点写入、双向一致。

## 三、数据模型（后端 settings 表，复用现有 KV）

| key | 值 | 默认 |
|-----|----|------|
| `proxy_sort` | defaultsort \| nameasc \| namedesc \| latencyasc \| latencydesc | latencyasc（原版截图当前值） |
| `proxy_group_by_provider` | 0 / 1 | 1（原版截图为开） |
| `proxy_card_min_width` | 整数 px | 155 |
| `proxy_display_order` | JSON 数组（站点集名，如 ["Speed","AI",...,"其他"]） | 空 = 按站点集原生顺序 |

API（复用现有 settings 读写习惯）：
- `GET /api/openbox/proxy-settings` → `{sort, group_by_provider, card_min_width, display_order[]}`
- `PUT /api/openbox/proxy-settings` → 部分更新，写 settings 表
- 命中排序不需要新接口：前端用现有 `/api/sitesets`（带 position 顺序）+ 前置规则是否存在（`GET /api/front-rules` 非空即显示 🚩 前置自定义分流置顶）拼出只读列表

## 四、前端实现

### 4.1 入口按钮
`ObProxiesView.vue` 顶部栏搜索框右侧加设置按钮（图标用原版同款剪刀/齿轮，`title=策略设置`）。点击打开 `ProxySettingsModal.vue`。注意：按钮放在策略/节点 Tab 行，不进订阅 Tab（原版在代理页全局）。

### 4.2 `ProxySettingsModal.vue`（新组件，约 250 行）
布局照原版截图三段式：
1. **基础项**：排序下拉（5 选项）、分组开关（daisyUI toggle）、卡宽输入（number input + 重置按钮，重置=155）
2. **显示顺序**：可拖动列表（复用 SitesTab 前置规则已有的 ≡ 拖拽逻辑），数据源 = 当前 `visibleProxyGroups` 全量（不过滤搜索），拖完即时保存 `proxy_display_order`
3. **命中规则排序**：只读编号列表；首行 🚩 前置自定义分流（仅当前置规则非空时显示）；其余按 `/api/sitesets` 的 position 顺序；底部原版说明文案

保存策略：基础三项改动即时 PUT（无"确定"按钮，原版为即时生效形态）；关闭弹窗不丢状态。

### 4.3 生效接线
- **排序**：modal 打开时读服务端 `proxy_sort`，写入 `proxySortType`（`src/store/settings.ts` 已导出）；`sortProxies` 原生逻辑自动生效（含延迟历史的 `latencyMap`）。
- **卡宽**：写入 `minProxyCardWidth`，`ProxyNodeGrid` 原生生效。
- **分组**：不用原生 `groupProxiesByProvider`（数据源不对）；自研 `ObProxiesBySub.vue`：
  - 数据：`renderProxies`（组内节点名列表）+ `/api/nodes` 的 `tag → sub_name` 映射（`useAliveCount` 已有 `/api/health`，加一个轻量 `tag→sub_name` map，可复用 `ObOutboundSelector` 里已写的 JOIN 逻辑思路，但这里走 `/api/nodes` 一次拉全量，前端做 map）
  - 渲染：按 sub_name 分段，每段一个小标题（订阅名），段内用原生 `ProxyNodeGrid` + `ProxyNodeCard`
  - 无订阅的节点（直连/手动添加）归入"其他"/空标题段，排最后
  - 开关关闭时回退原生 `ProxiesContent`
  - 接入点：`ProxyGroup.vue` 第 35 行的 `:is=` 三元扩展，或在 `FailoverGroupExt`/`ObProxiesView` 层包一层（推荐后者，不动 zashboard 原生文件）
- **显示顺序**：`useProxyGroupFilter.ts` 的 `visibleProxyGroups` computed 后加一步重排：按 `display_order` 数组的索引排序，未在数组中的组（新增）按原相对顺序追加到末尾。

### 4.4 i18n
新增 keys（中/英/繁/日与其他管理页同步）：`obx.proxySettings`（策略设置）、`obx.nodeSort`（节点排序方式）、`obx.sortDefault/latencyAsc/...`（5 排序选项）、`obx.groupByProvider`（节点根据提供商分组）、`obx.cardMinWidth`（节点卡片最小宽度）、`obx.reset`（已有）、`obx.displayOrder`（显示顺序）、`obx.hitOrder`（命中规则排序）、`obx.frontCustomShunt`（前置自定义分流）、说明文案两段。

## 五、后端实现（`oss/panel/db.py` + `app.py`，约 40 行）

- `DEFAULT_SETTINGS` 加四项默认值（注意：`proxy_display_order` 默认空字符串）。
- `GET /api/openbox/proxy-settings`：读四个 settings，`display_order` JSON 解析失败回 []。
- `PUT /api/openbox/proxy-settings`：白名单校验后写入；`sort` 校验 5 取值；`card_min_width` 钳制 80~400；`display_order` 必须为数组。
- 无需 migration（settings 表已存在）。

## 六、验收标准

1. 点设置按钮弹窗三段与原版截图一致（含底部两段说明文案）。
2. 切排序为"按名称降序"，节点组内卡片顺序实时变化；刷新页面保持。
3. 关"按提供商分组"，节点恢复扁平 grid；开则按订阅分段（7 个链式代理节点不参与——它们不在策略组内）。
4. 卡宽改 200，卡片变宽；点重置回 155。
5. 拖动"显示顺序"把 Youtube 拖到首位，策略 Tab 的组卡片顺序实时变；刷新保持；新增策略组自动出现在末尾。
6. 「命中规则排序」与「设置 → 目标分流」的站点集顺序一致；前置规则清空后 🚩 行消失。
7. 无痕模式/换浏览器打开，设置保持（服务端持久化验证）。

## 七、诚实缺口与风险

- 原版排序下拉的**完整选项列表**未实测（截图只显示当前值"按延迟升序"），按 zashboard 原生 5 项映射；若原版选项不同需对照修正。
- 原生 `ProxiesByProvider` 弃用改自研，约 80 行新代码，是本方案唯一"造轮子"点，理由见二（数据源不兼容）。
- `display_order` 存的是组名；若用户重命名策略组，旧名残留数组——重排时忽略未知名（已处理），改名后的组视为"新增"排末尾，可接受。
- 故障转移组（FailoverGroupExt 包裹的）同样参与显示顺序重排；lane 子卡片不受影响。
