# 入口绕过（Entry Bypass）机制分析报告

> 分析日期：2026-10-19
> 分析人：Muse（子代理）
> 资料来源：
> - 第三方报告 v1：`panel-contract/behavior-spec.md §5.3`、`state-model.md`、`core-state-schema.json`、`i18n-en.json`
> - 第三方报告 v2：`panel-contract/state-model.md`（entryPlan/bypassPlan 签名）
> - REA 摘录：`oss/docs/rea-report-intel.md`
> - 我方代码：`oss/core/transparent.py`、`oss/core/singbox.py`、`oss/core/models.py`、`oss/panel/app.py`、`oss/panel/db.py`
> - 已屏蔽：`open-box-core-reversed.json`、`open-box-windows-reversed.json`（逆向产物，未使用）

---

## 一、原版完整机制（行为描述）

### 1.1 总开关

- 名称："直连不进内核"（Direct traffic bypasses the core）
- 默认值：开（ON）
- 开：直连流量在入口（nftables）即被放走，永不进入内核转发。吞吐可能翻倍；代价是内核看不到这部分流量——连接页、流量洞察、统计量都没有它们。
- 关：所有流量进内核。统计完整，但速度受内核转发能力限制。
- 文案依据：`directBypassDescription` / `directBypassTitle`（v1 i18n-en.json:1124-1125）

### 1.2 两种自动模式（开关开时生效，无需配置，自动选择）

| 模式 | 核心名 | 触发条件 | 行为 |
|---|---|---|---|
| Default-release（默认放行） | `blacklist` | FakeIP 开且兜底为直连 | 代理域名拿 FakeIP 占位地址必进内核；其余流量只要解析出的地址不在"进内核集合"（代理/拒绝站点集的 IP 集合）中，就在入口放行 |
| Default-enter（默认进入） | `whitelist` | 其他情况 | 只有当前直连站点集的 IP 集合（默认是"国内"分组的 geoip-cn 家族）才在入口放行；与代理集合重叠的网段先减去 |

关键点：
- 模式切换、站点集直连/代理翻转时，只重写规则集文件，内核不重启
- 规则页必须显示当前是哪个模式以及原因

### 1.3 entryPlan 接口（核心规划函数）

entryPlan(routing, {members, builtin, selections, clientRoutes, fakeIp, dnsMode, enabled})
返回 { mode: "blacklist|whitelist", reason: string, needSets: [], needCidrs: [], directAnswer: bool }

- mode：选中的模式
- reason：人类可读的原因字符串（规则页显示用）
- needSets / needCidrs：需要在入口放行的集合/CIDR
- directAnswer：是否启用 direct-answer release

另有 bypassPlan(同参数) 返回 { sets, pending[] }，其结果经面板哈希为 nativeBypassPlanKey，用于判断 nftables bypass 计划是否需要重新应用。

### 1.4 Direct-answer release（仅 default-release 模式）

解决的问题：入口只能看到 IP。直连站点若在 CDN 后面（如 Cloudflare），其地址可能落在代理集合内，无法区分。

机制：在把直连站点集和兜底的 DNS 应答交给设备之前，内核先把"本应进内核"的地址写入一个限时入口放行集合。这样当设备拿到地址发起连接时，连接已经在放行集合里——连首个连接也不进内核。

生命周期：
- 保留时长 = DNS 应答的缓存 TTL，但最少 15 分钟，最多 1 天
- 重启持久化：内核重启后保留，启动时按剩余时间重写
- 全部清空：站点集从直连→代理/拒绝，或路由设置变更时（与 dnsmasq 缓存一起清空）
- proxy→direct：只删除不再需要的地址（非全清）

### 1.5 直连设备（per-device routing = "direct"）

- 内核对首包做预判：若未命中代理/拒绝 IP 范围、前置自定义规则的规则集和端口，则在入口放行，整条连接不进内核
- 已经在外部的连接不再预判（多 WAN 线路选择不受影响）
- 按设备 DNS：内核按设备分别应答 DNS，返回真实直连地址（dnsmasq 模式下也如此）
- 设为"不进内核"的设备同样获得按设备 DNS；若意外拿到 FakeIP 占位，连接仍正常进内核（永不连不上）

### 1.6 节点服务器地址

"订阅与节点站点直连"下的节点服务器地址，同样通过首包预判在入口放行。

### 1.7 必须明示的已知限制

- 站点集直连→代理翻转后，设备本地 DNS 缓存中仍有效的真实 IP 会继续走直连
- 设备自用 DoH，或 FakeIP 开启前已缓存的真实 IP，不在保证范围内

### 1.8 验收标准（原版）

- 模式自动选择，并在规则页报告模式及原因
- 模式/翻转变更永不重启内核
- direct-answer 集合遵守 15 分钟/1 天边界，重启后保留
- direct→proxy 时清空集合并连带清空 dnsmasq 缓存

---

## 二、我们当前实现的差距

### 2.1 已有（基础规则）

| 功能 | 位置 | 说明 |
|---|---|---|
| `direct_bypass_kernel` 设置 | `oss/panel/db.py:284` | 默认值 "0"（关） |
| 直连域名 ipset | `oss/panel/app.py:1442` | 开启时收集直连站点集域名 → `direct_ipset_domains` |
| nftables ipset 放行 | `oss/core/transparent.py:158` | dnsmasq 把直连域名解析 IP 写入 ipset，入口 accept |
| 旧前端开关 | `oss/panel/frontend/src/views/Settings.vue` | 旧版 UI 有开关 |
| i18n 文案 | zashboard `zh.ts:356-357` | `directBypassKernel` / `directBypassHint` |

### 2.2 缺失（与原版的差距）

| # | 原版能力 | 我们现状 | 差距等级 |
|---|---|---|---|
| 1 | 总开关默认开 | 默认 "0"（关），且新版 zashboard 前端**无此开关** | 🔴 高 |
| 2 | 自动模式选择（blacklist/whitelist） | 无。我们的 ipset 方案近似于 whitelist 的简化版，但无 FakeIP 联动的 blacklist 模式 | 🔴 高 |
| 3 | entryPlan（mode/reason/needSets/needCidrs/directAnswer） | 无对应规划函数 | 🔴 高 |
| 4 | 规则页显示模式及原因 | 无 | 🟡 中 |
| 5 | Direct-answer release 集合 | 无 | 🔴 高 |
| 6 | Release 集合 TTL（15min~1天） | 无 | 🔴 高 |
| 7 | Release 集合重启持久化 | 无 | 🔴 高 |
| 8 | direct→proxy 时清空集合+dnsmasq 缓存 | 无（我们 flip 时是否清 dnsmasq 缓存待确认） | 🟡 中 |
| 9 | 直连设备的首包预判 | 终端分流有 proxy/direct/bypass 三策略，但"首包预判进内核集合"逻辑缺失 | 🟡 中 |
| 10 | 按设备 DNS（返回真实直连地址） | 无 | 🟡 中 |
| 11 | 节点服务器地址的首包预判放行 | `sub_node_direct` 有 obnode-direct rule_set，但那是路由层面的，非入口 nftables 预判 | 🟡 中 |
| 12 | 模式/翻转不重启内核 | 站点集翻转已实现热切换（不重启），符合 | ✅ 已有 |
| 13 | 已知限制的明示 | 无 | 🟢 低 |

### 2.3 架构层面的根本差异

原版是 **Go 核心引擎**（`openbox/engine` 包）统一计算：
`panel → entryPlan/bypassPlan → {nftables 计划 + sing-box 配置}`

我们是 **Python 直算 + nftables 模板**：
- nftables 规则由 `transparent.py` 模板生成
- sing-box 配置由 `singbox.py` 生成
- 两者之间没有统一的"规划"层

补齐时不需要照搬 Go 架构，但需要在 Python 侧建立一个等价的规划函数（`entry_plan()`），输出模式、原因、放行集合，供 `transparent.py` 和前端展示使用。

---

## 三、补齐的完整 TODO

### 阶段 A：数据模型与设置（后端基础）

- [ ] A1. `oss/panel/db.py`：`direct_bypass_kernel` 默认值从 `"0"` 改为 `"1"`（对标原版默认开）
  - 注意：需评估存量用户的影响（突然开启可能改变流量路径）。建议加迁移逻辑：只有新安装默认开，已有配置保持原值。
- [ ] A2. 新增设置项 `entry_bypass_mode_display`（无需持久化，运行时计算）
- [ ] A3. 新建 `oss/core/entry_plan.py`（或并入 `routing.py`）：
  ```python
  @dataclass
  class EntryPlan:
      mode: str          # "blacklist" | "whitelist" | "off"
      reason: str        # 人类可读原因（中英文）
      need_cidrs: list[str]   # 入口放行的 CIDR
      need_sets: list[str]    # 入口放行的 ipset 名
      direct_answer: bool     # 是否启用 direct-answer

  def entry_plan(cfg) -> EntryPlan:
      """对标原版 entryPlan。
      blacklist 条件：fakeip 开启 且 兜底动作为 direct
      whitelist：其他情况
      off：总开关关闭
      """
  ```
- [ ] A4. `reason` 文案需要中英双语（参考原版 `routeEntryBypass*` 系列 i18n key 的风格）

### 阶段 B：Direct-answer release 集合

- [ ] B1. 数据模型：新建表 `direct_answer_set`（或复用内存+文件）：
  ```
  表：direct_answer_ips
  - ip: TEXT PRIMARY KEY（CIDR 或单 IP）
  - expires_at: INTEGER（Unix 时间戳）
  - source: TEXT（哪个站点集/DNS 应答引入的，用于 proxy→direct 时的精准删除）
  ```
- [ ] B2. TTL 规则：`clamp(dns_ttl, 15*60, 24*3600)`，即最少 15 分钟、最多 1 天
- [ ] B3. 写入时机：内核（或面板代理 DNS 流程）在向设备返回直连站点集/兜底的 DNS 应答**之前**，把应答中的 A/AAAA 地址写入集合
  - 技术路线待定：sing-box 无原生钩子，可能需要在面板侧 DNS 查询日志/代理逻辑中实现，或通过 dnsmasq 的 `ipset=` 联动
  - 简化方案 v1：面板在 `dnslog` 中观察到直连域名的解析结果时，异步写入 nftables set
- [ ] B4. 重启持久化：面板启动时从表重建 nftables set，`expires_at` 按剩余时间重写（已过期的不重建）
- [ ] B5. 清空规则：
  - 站点集 direct→proxy/reject 时：清空整个集合 + 清 dnsmasq 缓存
  - 路由设置变更时：同上
  - 站点集 proxy→direct 时：只删除 `source` 属于该站点集的条目
- [ ] B6. nftables 模板：在 `transparent.py` 中新增 `direct_answer` set，`prerouting` 链中优先 accept

### 阶段 C：模式联动的 nftables 生成

- [ ] C1. `transparent.py` 的 `TransparentConfig` 新增字段：
  - `entry_mode: str`（"blacklist"/"whitelist"/"off"，由 `entry_plan()` 填入）
  - `entry_cidrs: list`（放行 CIDR）
  - `direct_answer_set: str`（set 名，供模板引用）
- [ ] C2. blacklist 模式的 nftables 逻辑：
  - 代理/拒绝站点集的 IP 集合 → "进内核集合"
  - 除此之外的流量在入口 accept（默认放行）
  - 注意：不能简单 `accept all`，仍需保留现有 bypass4/bypass6、终端规则、端口规则的优先级
- [ ] C3. whitelist 模式的 nftables 逻辑（接近现有实现）：
  - 直连站点集的 IP 集合（默认 geoip-cn）→ 入口 accept
  - 与代理集合重叠的网段先减去（nftables set 的 `flags interval` + 排除逻辑，或拆分为多条规则）
- [ ] C4. `app.py` 中生成 `TransparentConfig` 时调用 `entry_plan()`，不再用简单的 `direct_bypass` 布尔

### 阶段 D：前端（zashboard）

- [ ] D1. 在设置页（或透明代理设置区）恢复"直连不进内核"总开关
  - 文案直接复用已有 `directBypassKernel` / `directBypassHint`
  - 补充 FakeIP 联动提示：`directBypassNeedsFakeIp`（"FakeIP 关闭时，域名匹配的直连目标无法在入口区分，仍会进内核走直连"）
- [ ] D2. 规则页（目标分流页）新增"入口绕过状态"展示区：
  - 当前模式：默认放行 / 默认进入 / 已关闭
  - 原因：`entry_plan().reason`
  - 样式参考原版（behavior-spec §5.3："The rules page states which mode is active and why"）
- [ ] D3. 新增 API：`GET /api/openbox/entry-plan` 返回 `EntryPlan` 的 JSON（供前端展示）
- [ ] D4. i18n 补 key（四语言）：
  - `entryBypassModeBlacklist` / `entryBypassModeWhitelist` / `entryBypassModeOff`
  - `entryBypassReason*` 系列（原因文案）
  - 已知限制提示文案

### 阶段 E：直连设备的首包预判与按设备 DNS

- [ ] E1. 终端设为 "direct" 时，nftables 首包预判规则：
  - 若目标 IP 未命中代理/拒绝集合、前置规则的集合/端口 → 入口 accept
  - 已在外部的连接（established）跳过预判
- [ ] E2. 按设备 DNS：内核（或 dnsmasq+面板联动）按设备分别应答，直连设备返回真实地址而非 FakeIP
  - 技术路线：dnsmasq 按 MAC/IP 的 `dhcp-option` 分流较复杂；简化方案 v1 可在面板 DNS 代理层按源 IP 区分
- [ ] E3. "不进内核"设备同样获得按设备 DNS；FakeIP 误发时回退进内核（永不连不上）

### 阶段 F：验证

- [ ] F1. 单元测试：`entry_plan()` 的模式选择逻辑（FakeIP 开/关 × 兜底 direct/proxy × 总开关）
- [ ] F2. TTL 边界测试：15 分钟下限、1 天上限、过期清理
- [ ] F3. 重启持久化测试：写入条目 → 重启面板 → nftables set 重建且剩余时间正确
- [ ] F4. 清空规则测试：direct→proxy 翻转后集合清空 + dnsmasq 缓存清空
- [ ] F5. 真机验证：Default-release 模式下 CDN 背后的直连站点首连不进内核

---

## 四、风险与建议

1. **B3（direct-answer 写入时机）是最大技术风险**。sing-box 无原生钩子在 DNS 应答前写 nftables set。建议分两期：
   - v1：面板侧异步写入（`dnslog` 观察 + 延迟写入，首连可能仍进内核一次，诚实标注为"近似实现"）
   - v2：探索 sing-box 的 `ipset` 或外部脚本联动

2. **A1 的默认值变更需谨慎**。存量用户突然从"全进内核"变为"直连不进内核"，流量路径变化大。建议：
   - 新安装默认开
   - 已有用户保持原值，升级时在更新日志中提示

3. **不要碰 reversed 文件**。本报告所有行为描述均来自 behavior-spec/state-model/i18n 等行为契约，未使用反汇编产物。

4. **优先级建议**：A（规划函数+开关）→ D（前端展示）→ C（nftables 联动）→ B（direct-answer）→ E（按设备）。A+D 即可让用户看到"模式及原因"，是性价比最高的第一步。
