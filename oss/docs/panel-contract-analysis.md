# Open-Box 闭源研究报告分析 — 对开源面板开发的价值评估

> 分析对象：`/tmp/obx-report/panel-contract/`（第三方大模型研究报告）
> 分析日期：2026-10-18
> 结论前置：**这份报告极具价值**，是目前最完整的原版行为契约。它补上了我们之前靠黑盒猜测的多个关键空白，特别是：完整的 122 端点清单、81 个路由判定黄金用例、43 个分享链接解析用例、以及 sing-box 标签命名规范（含我们尚未实现的 `obflip-byp-*`、`obflip-need-*` 等）。

---

## 一、端点覆盖率对比（报告 122 个 vs 我们 194 个）

说明：我们端点多是因为同时保留了 `/api/*` 和 `/api/openbox/*` 两套路径。以下按功能分组对比，以**功能覆盖**为准（路径不同不算缺失）。

### ✅ 已覆盖（功能对等）

| 功能组 | 报告端点 | 我们对应实现 | 备注 |
|---|---|---|---|
| 认证 | POST /api/auth/login/logout, GET status | ✅ 相同 | 缺 setup/change-password（见下） |
| 订阅管理 | GET/POST/DELETE/PATCH /api/openbox/subscriptions*, preview, order, :id/refresh | ✅ /api/subscriptions* + /api/openbox/subscriptions/preview | 另有 speedtest/nodes 等扩展 |
| 订阅分享 | GET/POST/DELETE/PATCH /api/openbox/subscription-shares*, regenerate | ✅ 两套模型并存 | 需合并（已知缺口） |
| 分组管理 | GET/PUT /api/openbox/groups | ✅ /api/groups 全套 CRUD | |
| DNS 基础 | flush-cache, region-detect(GET+POST), upstream-test, wan | ✅ 全部有 | 路径部分为 /api/dns/* |
| DNS 过滤 | GET/PUT, apply, preview, records | ✅ 全部有 | 缺 summary（见下） |
| 故障转移 | recheck, refresh, status | ✅ 全部有 | |
| 规则穿透 | POST /api/openbox/penetration | ✅ 相同 | |
| 路由测试 | POST /api/openbox/route-test | ✅ /api/route/test | |
| 节点信息 | GET node-info/:tag, entry-country, POST exit | ✅ 全部有 | |
| 流量统计 | day/month/usage/drill | ✅ 全部有 + now | |
| 延迟历史 | GET, POST samples, POST sync | ✅ 全部有 | 缺 version |
| 站点延迟 | GET/POST, history | ✅ 全部有 | |
| 终端测试 | POST terminal-test, GET capability | ✅ 全部有 | 真实探测已实现 |
| 系统时区 | GET/PUT | ✅ /api/system/timezone | |
| 诊断 | GET /api/openbox/diagnostics | ✅ /api/diagnostics | |
| 订阅链接 | GET /sub/:token | ✅ 相同 | |
| 出厂重置 | POST factory-reset | ✅ /api/factory-reset | 路径不同 |
| 回滚 | POST rollback | ✅ /api/deploy/rollback | 路径不同 |

### ❌ 缺失端点（按优先级排序）

#### P0 — 影响核心功能对标

| 报告端点 | 用途 | 我们的状态 | 建议 |
|---|---|---|---|
| `GET /api/openbox/profile` / `PUT` | 整个面板配置的读写（原版所有管理配置存在一个 profile JSON） | ❌ 无。我们用分散的表+ `/api/settings` | **建议实现为兼容层**：GET 聚合返回 settings+groups+sitesets 等，PUT 分发写入。第三方客户端可能依赖此端点 |
| `GET /api/openbox/nodes/latency` (POST) | 批量节点延迟测试 | ❌ 无。我们只有 /api/health/check | 建议实现：与 health/check 语义接近，可做薄封装 |
| `GET /api/openbox/nodes/latency/queue` | 延迟测试队列状态 | ❌ 无 | 与上一个配套实现 |
| `POST /api/openbox/chain-proxies/latency` | 链式代理延迟测试 | ❌ 无。我们有 /api/chains/:id/speedtest（真实拨测） | 功能已覆盖，路径不同。建议加别名 |
| `GET /api/openbox/kernel/version` | 内核版本查询 | ❌ 无 | 简单实现：返回 sing-box --version |
| `GET /api/openbox/config/preview` | 配置预览（不落盘） | ⚠️ 部分。/api/config 返回已生成配置 | 建议加 preview 参数 |

#### P1 — 影响完整性

| 报告端点 | 用途 | 我们的状态 |
|---|---|---|
| `GET /api/openbox/dns-filter/summary` | DNS 过滤摘要统计 | ❌ 无 |
| `GET /api/openbox/policies/entries` | 策略条目列表 | ❌ 无 |
| `GET /api/openbox/defaults/groups` / `defaults/routing` | 默认分组/路由 | ❌ 无（我们硬编码了 12 个默认站点集） |
| `GET /api/openbox/rulesets/entries` / import / preview | 规则集条目管理 | ⚠️ 部分（我们有 /api/rulesets CRUD） |
| `POST /api/auth/setup` | 首次设置密码 | ❌ 无（我们部署时直接设密码） |
| `POST /api/auth/change-password` | 修改密码 | ⚠️ 有 /api/auth/password（语义接近，需核对） |
| `GET /api/openbox/latency-history/version` | 延迟历史版本 | ❌ 无 |
| `POST /api/openbox/deploy` | 部署 | ⚠️ 有 /api/deploy/state，无 POST deploy |
| `GET /api/openbox/update/notes` | 更新说明 | ❌ 无 |
| `POST /api/openbox/update/cancel` | 取消更新 | ❌ 无 |

#### P2 — 低优先级 / 明确不在范围

| 报告端点 | 说明 |
|---|---|
| `/api/openbox/activation` (GET/POST/PUT/DELETE) | 激活（Ed25519）。**明确不在复刻范围** |
| `/api/openbox/license` (GET/POST/DELETE) | 许可证。**明确不在复刻范围** |
| `/api/openbox/tutorial-videos` | 教程视频，可不做 |
| `/api/background-image` (GET/PUT/DELETE) | 背景图，纯 UI 偏好 |
| `/api/storage` (GET/PATCH/PUT) | 通用 KV 存储。原版用它存 profile；我们用 SQLite 表，已覆盖功能 |
| `/api/openbox/client-app/*` | 桌面客户端配套，可不做 |
| `/client/v1/:routerId/*` (10个) | 客户端协议。**只有 /api/client/* 需按公开协议对齐**，v1 路径需核对 |

---

## 二、路由测试用例分析（routing-golden.json，81 个）

### 用例结构

每个用例 = `{id, group, desc, input, expected}`：

- **input**：`obclient.predictInput` 负载 = `{target, config}`。target 是待判定的域名/IP，config 是精简版 sing-box route（rules + final）。
- **expected**：`{index, action, outbound, hits, text, final, port, isIp, entry}`。index 是命中的规则序号（1-based，0=未命中走 final）；hits 记录命中的条件种类；entry 描述入口模式。

### 16 个分组覆盖的行为

| 分组 | 数量 | 关键行为 |
|---|---|---|
| domain / domain_suffix / domain_keyword / domain_regex | 17 | 精确/后缀/关键字/正则四种域名匹配语义 |
| ip_cidr | 11 | CIDR 匹配 |
| ip_is_private | 19 | 私有 IP 判定（数量最多，说明原版重度依赖） |
| ip_version | 3 | IPv4/IPv6 区分 |
| port / port_range | 7 | 端口与端口段 |
| rule_set | 4 | 规则集引用 |
| **ordering** | 4 | **先匹配者胜**：第一条命中即返回；无命中 index=0 走 final |
| final | 3 | 兜底行为 |
| invert | 2 | `invert: true` 反转匹配 |
| action | 3 | `route` / `reject` / 缺省=route |
| and | 3 | 多条件 AND（逻辑规则） |
| table | 5 | 复合查表 |

### 对我们的启示

1. **ordering 组证实了我们已实现的行为**：`order-first-wins`（第一条匹配胜出）、`order-none-fallthrough`（无命中走 final，index=0）。我们的 `build_route_rules` 按站点集顺序生成规则，与 sing-box 先匹配者胜语义一致。✅
2. **`ip_is_private` 有 19 个用例**：原版对私有 IP 有精细处理（对应我们规则 42 `ip_is_private=true → 直连`）。建议检查我们的私有 IP 判定是否覆盖了 sing-box 的全部私有段（10/8、172.16/12、192.168/16、127/8、::1、fc00::/7 等）。
3. **`invert` 行为**：我们的前置规则和站点集是否支持 `invert`？报告显示原版规则 1、24、28 等大量使用 `!(...)` 反转条件。**这是我们可能缺失的语义** —— 我们的 SiteSet 模型没有 `invert` 字段。建议在前置规则的 8 种类型中增加"反选"选项。
4. **无 obflip 相关用例**：obflip 是面板/核心层的构造，不是路由判定层的语义，符合预期。

---

## 三、分享链接格式分析（sharelink-cases.json + sharelink-golden.json）

### 测试覆盖

43 个用例，覆盖协议：vless（9）、trojan（3）、vmess（4）、ss（6）、hysteria2（5）、tuic（2）、anytls（1）、socks（5+2），以及 8 个非法链接。

### 关键发现

1. **桌面客户端只支持 5 种协议**：vless、shadowsocks、hysteria2、tuic、socks5。22 个用例因"桌面不支持"被标记为 `comparable: false`（含 trojan、vmess、anytls 等）。
   - **对我们的意义**：我们的 Python 解析器支持 ss/vless/trojan/vmess/tuic/hysteria2/anytls（7 种），**比桌面端更全**。这是优势，不是缺口。但要注意：与桌面端行为对标时，trojan/vmess/anytls 的解析细节应以**面板**（index.mjs 7311-7360 转录的 `source_derived` 期望）为准，报告已注明"面板胜出"原则。

2. **解析期望的字段映射**（以 vless-ws-tls 为例）：
   ```
   vless://uuid@host:port?type=ws&path=/ws&host=a.example.com&security=tls&sni=b.example.com#tag
   → {type: vless, uuid, server, server_port, tls: {enabled, server_name: sni}, transport: {type: ws, path, headers: {Host}}}
   ```
   建议用这 43 个用例做我们解析器的回归测试，逐个比对字段。

3. **非法链接处理**：8 个 invalid 用例（坏 scheme、缺端口、坏传输、vmess JSON 非法、reality 缺 pbk）。我们的 `is_info_node()` 过滤了假节点，但**非法链接的拒绝行为**值得用这些用例验证。

---

## 四、sing-box 标签命名规范（singbox-tags.json + singbox-contract.md）

### 我们已对齐的

| 标签 | 报告定义 | 我们 |
|---|---|---|
| `__fo:reject` | 故障转移 reject 回退，`__fo:` 前缀在链路列表隐藏 | ✅ 已实现 |
| `obflip-<sha256(id\|name)[0:12]>` | 每站点集翻转规则集，`Lo + sha256(...).slice(0,12)` | ✅ 已实现（刚完成） |
| `builtin-direct` / `builtin-block` / `all-auto` | 内置组 | ✅ 概念有（命名为 direct/block/所有-自动，功能等价） |
| `direct` / `block` | sing-box 保留 | ✅ 使用 |

### 我们缺失的（重要）

| 标签 | 报告定义 | 影响 | 优先级 |
|---|---|---|---|
| `obflip-byp-<policy>` | 每策略 bypass 集合（前缀常量 `Ff`） | 原版规则 1 的 `bypass()` 依赖它。我们的"入口绕过"用 nftables 实现，**架构不同**，但若客户端查询此 rule_set 会 404 | P1 |
| `obflip-fallback` | fallback 策略的翻转集（常量 `Fo`） | 兜底策略的 QUIC 拦截（原版规则 77）引用它。我们当前没有 fallback 的 QUIC 规则 | P1 |
| `obflip-need-all` / `obflip-need-fakeip` / `obflip-need-cidr` | 黑洞入口辅助（0.0.0.0/0、FakeIP 段、直连 CIDR） | TUN 入口控制。我们的透明代理用 nftables + 自动路由，机制不同 | P2（架构差异，可不做） |
| `obflip-off.invalid` | "站点集关闭"时的哨兵域名（永不匹配） | 禁用站点集时原版用此哨兵保持规则结构。我们是直接不生成规则，行为等价 | P2（可不做） |
| `obnode-direct` / `obnode-direct-ip` | 直连域名/CIDR 集合（rule_set） | 原版规则 44 `rule_set=[obnode-direct obnode-direct-ip] → 直连`。我们有 `sub_node_direct` 但用的是内联 `domain_suffix`，**没有这两个 rule_set 标签** | P1 |
| `dns-direct` / `dns-proxy` / `dns-fakeip` 等 | DNS 传输/服务器标签体系 | 我们的 DNS 服务器标签是 `direct-dns`/`proxy-dns`/`fakeip`，与原版 `dns-direct`/`dns-proxy`/`dns-fakeip` **命名不同**。若第三方工具按标签查询会不兼容 | P1 |
| `openbox-tun` | TUN 入站标签 | 我们用的可能是 `tun-in`。内核的 tun input-mark 逻辑引用此标签 | P1（需核对） |
| `dns-in-direct` / `dns-in-lan` | DNS 入站 | 我们没有独立的 DNS 入站（用 hijack-dns）。原版规则 3 `inbound=dns-in → hijack-dns` 表明原版有专用 DNS 入站 | P2（架构差异） |

### config 渲染的关键纠正

`singbox-contract.md` §2 明确：**内核配置不是面板组装的，是 Go 核心（openbox/routercore）经 `configDetailed` RPC 渲染的**。面板只传 16 个键的 state，收回 `{config, dnsRuleOwners, directHosts, failover}`。

这验证了我们 Python 面板侧自研渲染器的架构合理性（我们本来就是自己渲染），但也意味着：**逐字段对齐原版 config 是不可能的**（Go 核心逻辑未公开），只能对齐可观察行为（规则顺序、标签命名、API 语义）。我们当前"行为对标"的路线是正确的。

---

## 五、i18n 对比

- 报告：`i18n-en.json` **1753 keys**（behavior-spec 称 1,753 keys × 3 locales）
- 我们：979 keys（四语言已同步）
- 缺口约 774 keys，对应未实现功能（profile、license、tutorial-videos、background-image 等 P1/P2 端点背后的 UI）

---

## 六、综合优先级建议

### 建议立即做的（P0）

1. **`GET /api/openbox/profile` 兼容层** — 聚合现有数据返回，PUT 分发写入。第三方客户端/桌面端可能依赖。
2. **`GET /api/openbox/kernel/version`** — 一行实现，补齐诊断链。
3. **DNS 标签重命名**：`direct-dns`→`dns-direct`、`proxy-dns`→`dns-proxy`、`fakeip`→`dns-fakeip`（或保留旧名做别名）。标签是跨组件契约，命名差异是真实兼容性风险。
4. **`obnode-direct` / `obnode-direct-ip` rule_set** — 补上这两个标签的 rule_set 声明，把 `sub_node_direct` 的内联规则迁过去。
5. **TUN 入站标签核对** — 确认我们的 tun inbound tag 是否为 `openbox-tun`，不是则改。

### 建议随后做的（P1）

6. `obflip-byp-<policy>` 与 `obflip-fallback` — 补齐 QUIC 拦截的最后两块（bypass 与 fallback）。
7. `/api/openbox/nodes/latency` + queue — 薄封装 health/check。
8. 前置规则增加 `invert`（反选）支持 — 路由黄金用例证明原版重度使用。
9. `ip_is_private` 全段覆盖检查 — 19 个用例暗示的精细语义。
10. 用 43 个 sharelink 用例做解析器回归测试。

### 可不做的

- activation/license（明确排除）、tutorial-videos、background-image、storage（功能已覆盖）、obflip-need-*（架构差异）、obflip-off.invalid（行为等价）。

---

## 七、对报告本身的评价

**价值**：⭐⭐⭐⭐⭐（5/5）

- 122 端点清单是我们之前没有的（我们靠黑盒试出约 40 个）。P0 缺失的 profile/kernel-version 等端点若不看报告很难发现。
- 81 个路由黄金用例把"先匹配者胜""invert""ip_is_private"等语义钉死了，可直接转为我们的回归测试。
- 43 个分享链接用例是现成的解析器测试集。
- 标签规范揭示了 `obflip-byp-*`、`dns-direct` 等我们完全不知道的命名，是补齐 1:1 的最后拼图。
- `singbox-contract.md` 对"配置由 Go 核心渲染"的论证，终结了"要不要逐字段对齐 config"的纠结。

**局限**：
- 报告基于 v0.1.330，我们对标的是 v0.1.331（差异小）。
- 部分"oracle"是桌面 Go 解析器而非面板行为，报告已用 `comparable` 标记区分，可信度处理得当。
- Go 核心的渲染逻辑仍是黑盒（3,243 个函数），报告只给了边界，没有给出渲染算法 —— 这部分仍需行为对标。
