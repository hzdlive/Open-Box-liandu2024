# 第三方研究报告 v3 分析（Open-Box-liandu2024-3.zip）

> 解包：335 文件，121MB（zip 8MB）；对照基线为 v2（1084 文件，19MB）。
> 评级：**B+**（与 v2 持平；新增价值集中在默认规则集、RPC 方法面、两套金标准语料）。

## 一、结构与体量说明

- `README.md`：官方仓库说明文本（v0.1.330  era 产品说明），非分析报告。
- `rea-tools/`：REA 分析工具链（probe 脚本、i18n、enums、failover-engine）。
- `openbox-panel/`：原版面板 Node.js 实现全套（`src/`）+ 运行数据（`data/zashboard.sqlite*`）+ 默认值（`defaults/`）。
- `panel-contract/`：行为契约（路由、分享链接、RPC、i18n、schema）。
- `docs/pic/`：官方截图。
- 体量大头是 `.tmp/big*.json`（约 100MB），内容为 `{format: "x", pad: <1.2MB 填充>}`——尺寸上限测试夹具，无业务信息。

## 二、与 v2 字节相同的内容（无新增）

| 文件 | 结论 |
|------|------|
| `open-box-core-reversed.json`（capstone 反汇编） | MD5 与 v2 相同，**继续屏蔽** |
| `open-box-windows-reversed.json`（NSIS 逆向） | MD5 与 v2 相同，**继续屏蔽** |
| `rea-tools/failover-engine.json` | 与 v2 相同（`failover_function_map` 仍不可用，`state_schema`/`decision_reasons` 可用） |
| `rea-tools/ob-i18n-additions.txt`（1610 keys） | 与 v2 相同 |
| `open-box-rea-report.html/.zh.html` | 我们自己的 REA 报告再次混入，非第三方新增 |

## 三、v3 真新增（可用）

### 3.1 原版默认内容过滤规则集（最重要）

`openbox-panel/defaults/content-filter.json`：3 条默认规则集，全部 `enabled: true`，字段与我们的 `cf_rulesets` 表一一对应（id 16 位 hex、name、dialect、sourceUrl、text、rules、hostnames、arguments、scripts、enabled、updatedAt、skipped*）。

| 名称 | 方言 | 规则数 | 来源 | 更新 |
|------|------|--------|------|------|
| 综合省流 | quantumultx | 496 | https://yfamilys.com/rewrite/adlite.conf（APP 启动页去广告 lite） | 2026-08-25 |
| Youtube-Surge | surge | 3 | https://raw.githubusercontent.com/Maasea/sgmodule/master/YouTube.Enhance.sgmodule | 2026-09-23 |
| Youtube-补丁 | surge | 1 | （无外部源，自有补丁，针对 iOS YouTube 首页推荐流广告） | 2026-09-24 |

**直接回答待拍板问题**：原版确实预置默认规则集，"恢复默认"功能的实现目标就是这 3 条。
**合规注意**：规则文本是第三方作者内容（yfamilys、Maasea）及原版自有补丁，**不应把文本直接复制入库**；实现"预置"时应走"记录来源 URL + 首次拉取"或"仅预置元数据"路线，由用户自行决定。

### 3.2 核心引擎 RPC 方法面

`panel-contract/core-rpc-methods.json` + `core-rpc-args.json`：14 个方法（位置参数调用）：

`activationState`, `builtinTags`, `bypassPlan`, `checkActivationCode`, `classes`, `configDetailed`, `emitGroups`, `entryPlan`, `forwardPlan`, `migrateStoredRouting`, `normalizeGroups`, `normalizePolicy`, `normalizeRouting`, `routingFingerprint`

- 新发现：`bypassPlan`（入参含 routing/members/builtin/selections/clientRoutes/fakeIp/dnsMode/enabled）与 `forwardPlan`（含 rewriteDomains）是入口旁路与转发计划的两个独立 RPC——与我们已实现的 `entry_plan` 对应，值得对照检查覆盖面。
- `normalizeRouting` / `normalizeGroups` / `normalizePolicy` / `routingFingerprint`：配置规范化与指纹，交叉验证用。
- `activationState` / `checkActivationCode`：授权机制，**屏蔽**（不在复刻范围）。

### 3.3 路由金标准 81 测例

`panel-contract/routing-golden.json`：81 个路由匹配测例（2026-10-16 生成于 sing-box 1.14.1-openbox-tcp24），覆盖 domain exact/suffix、大小写不敏感、深子域名等。可用于抽查我们的 `penetration.py` 匹配逻辑。

### 3.4 分享链接金标准 43 测例

`panel-contract/sharelink-golden.json`：43 个分享链接解析测例，可用于之前待办的分享链接 conformance 验证。

### 3.5 配置组装预言机文档

`panel-contract/oracle-config-assembly.md`：记录桌面二进制 `openbox-core.exe` 通过 `experimental/obclient` 暴露的 `full-config` / `share-config` 两个可执行预言机及输入结构 `obclient.fullInput`。结论与 REA 一致（配置由核心引擎渲染而非面板），但需桌面二进制才能执行，**仅作交叉验证参考**。

### 3.6 其余默认值文件

`openbox-panel/defaults/`：`profile-defaults.json`、`storage-defaults.json`、`test-sites.json`（测速站点）、`share-regions-default.json`（分享地区）、`tutorial-videos.json`——默认值对照参考。

## 四、屏蔽清单（延续 v2 原则）

- 两份 reversed JSON（字节同 v2）。
- `openbox-panel/src/**` 原版 Node.js 实现代码：**不可复制**，仅行为对照参考。
- 激活/验签相关（`activationState`、`checkActivationCode`）。
- `rea-tools/*.exe`（`gosyms2.exe`、`stub-core.exe`）及反汇编工具链（`disasm.py`、`arm64dis.py`、`nsis_carve*.py` 等）——逆向用途，不使用。
- 与黑盒实测冲突时以实测为准。

## 五、对下一步的建议

1. 默认规则集：把 3 条的元数据（名/方言/来源 URL）记下，等用户拍板是否预置；若预置走"来源拉取"路线。
2. 路由金标准 81 例：抽查 `penetration.py`（尤其 suffix 大小写与深子域名）。
3. `bypassPlan` / `forwardPlan`：对照我们 `entry_plan.py` + `transparent.py` 的覆盖面。
4. 分享链接金标准 43 例：与待办的 conformance 测试合并验证。
