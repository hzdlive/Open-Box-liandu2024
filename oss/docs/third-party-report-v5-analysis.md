# 第三方研究报告 v5 分析（Open-Box-liandu2024-5.zip）

- 来源：`workspace/user/files/Open-Box-liandu2024-5.zip`（437 条目，解压 123MB）
- 结论：**v4 的严格超集，零删除**。新增 23 个文件，9 个同名文件内容变更。
- 评级：**A-**（与 v4 持平；部署管线行为契约是自 v3 RPC 面以来最可直接用的增量）
- 路由面未变：122 路由 105 已实现 / 17 stub（与 v4 相同）；测试全量 **42 套件 / 2877 断言全绿**（v4 为 31 套件 / 2392 断言，新增 485 断言）

## 一、变更清单

### 新增 23 个文件

| 类别 | 文件 |
|---|---|
| 分析者备忘录 | `.workbuddy-ai/memory/2026-10-22.md`（Wave 5 #1–#10） |
| 部署校验 | `src/core/config-validate.mjs` + `test/panel-wave5-validate.mjs`（47 断言） |
| 启动验证 | `src/core/kernel-watch.mjs` + `test/panel-wave5-kernel-watch.mjs`（40 断言） |
| 规则集落地 | `src/core/ruleset-materialize.mjs` + `test/panel-wave5-rulesets.mjs`（27 断言） |
| 正则→后缀 | `src/core/regex-suffix.mjs` + `test/panel-wave5-regex-suffix.mjs`（57 断言） |
| 转发计划 | `src/core/forward-plan.mjs` + `test/panel-wave5-forward-plan.mjs`（21 断言） |
| DNS 接管 | `src/core/dns-takeover.mjs` + `test/panel-wave5-dns-takeover.mjs`（60 断言） |
| 启动循环 | `src/core/kernel-start.mjs` + `test/panel-wave5-kernel-start.mjs`（23 断言） |
| 部署前置 | `src/core/deploy-preflight.mjs` + `test/panel-wave5-preflight.mjs`（22 断言） |
| 部署组装 | `src/core/deploy-assembly.mjs` + `test/panel-wave5-deploy-assembly.mjs`（40 断言） |
| 部署编排 | `src/core/deploy-run.mjs` + `test/panel-wave5-deploy-run.mjs`（65 断言） |
| 热切换计划 | `src/core/deploy-flip.mjs` + `test/panel-wave5-deploy-flip.mjs` |

### 内容变更的 9 个同名文件

- `.workbuddy-ai/memory/MEMORY.md`（Wave 1–5、42 套件 / 2877 断言）、`TRAPS.md`（新增 194–202+ 条，见下）
- `openbox-panel/README.md`、`package.json`（包版本仍 0.1.0，**未提新 release 版本号**，基线仍按 v0.1.344）
- `src/core/config-preview.mjs`（`configState` 接受 `cacheFilePath`，部署路径与预览路径之别）
- `src/core/deploy.mjs`（补 `rollbackSummary`）、`deploy-artifacts.mjs`（断言 82→83）
- `src/core/profile.mjs`（修真 bug，见下）、`test/panel-wave4-deploy-artifacts.mjs`（fixture 改正）

## 二、Wave 5 十段摘要（部署流水线 `cy` + `vv`）

部署被切成三段：**preflight（前半五道闸门）→ assembly（中段）→ start（for(;;) + lateCrashWatch）**，
再由 `runDeploy`（`vv`）编排：拿锁 → 跑三段 → 推 mark 进度 → 放锁。

1. **校验阶段**：`sing-box check -c` + 逐出站/逐 endpoint 探测 + `vetOutbounds`（每轮摘掉一个坏节点）+
   自签证书（只看 `tls.certificate_path`，`sing-box generate tls-keypair`，私钥在前证书在后）。
2. **启动验证**：`logread -e sing-box` 读日志；FATAL 行判定；四路判定（buffer 重试 / settle 重试 / 降级 / 放弃）；
   降级是 `continue`（重建后下一轮重新 snapshot）；`autoRedirect` 必须回写。
3. **规则集落地**：`route.rule_set[].path` 改写成安装路径；两个 direct set 有变化才写；`obflip-` / `list-` 前缀常量。
4. **正则→后缀证明器**：迷你正则解析器（字面量/转义/`.`/字符类/`^$`/顶层 `|`/一层分组/量词）；预算 64 tails / 8 KiB / 2048 展开；
   任一规则集展不开 → 整体退回 `mode:"all"`（全有或全无，防静默泄漏）。
5. **转发计划**：`sing-box rule-set decompile`（输出在输入之前）→ 拍平合并 → `server=/<domain>/<local>`；
   排序必须稳定，否则"内容未变跳过写入"永远判变。
6. **DNS 接管（OpenWrt uci）**：备份先写；`plan=all` 意味着 uci 不再可信，只有备份能说出原始上游；
   查询日志永远不能搞挂部署（崩了就回滚 drop-in、再重启、写闩锁，`reason:"failed"`，部署继续）；
   空 drop-in 是删除不是写空。
7. **启动循环**：轮询 `[0, 3000]`（第一次立刻）；启动成功后的迟发崩溃监视（阶梯进入时选一次，中途降级不缩短剩余延迟）。
8. **部署前置**：五道闸门顺序是被逼的——冲突 → 规则集 → flip → 证书 → `sing-box check`；
   flip 失败延后上报（check 通过才报 error；配置也坏时 validate 赢）；`cancelled` 在 check 之后判；
   `timings` 省略规则：conflict/两种 validate 不带，rulesets/error/cancelled 带。
9. **部署组装**：四个计划先算完再落盘；顺序 config + sidecar → entry-bypass.nft → DNS → uci 防火墙；
   DNS 把计划从 domains 降级成 all、或 queryLog 状态翻转 → **重写两份文件，不是打补丁**；
   三道闸门（取消 / 缺二进制 / 缺 `/dev/net/tun`）每道都 teardown 并把 rollbackSummary 拼进消息。
10. **部署编排**：重试是**重建**不是打补丁（`skipNodes` 进构建输入，第二轮配置里根本没有坏节点）；
    `badTags` 和 `warning` 互斥（成功→跳过节点进 warning；失败→并进 badTags，不再加 warning）；
    自启在 try/catch 之外（写自启失败不能把成功部署变成失败部署）。
    附带确认：`cy` 中段几乎全是 native core 的 RPC（`forwardPlan` / `bypassPlan` / `routingFingerprint` / `classes`），
    即每次调用 spawn 一次 `native/openbox-core` 的桥（带 buildID 校验）——中段在本实现里是对 `ops` 的编排，不是新纯逻辑。

## 三、屏蔽项（重申，与 v4 相同）

- 两份 reversed JSON 与 v4 **字节相同**（MD5：core `48fe1849e8bcbab1db4373a4edbc0c0d`，
  windows `2cf4a789916194e1afd8ccb85dc47175`），继续屏蔽，不可用。
- `src/` 全部为反混淆实现：仅行为对照，不复制。`rea-tools/*.exe` 不使用。
- 与黑盒实测冲突时以实测为准。

## 四、顺手修的真 bug（分析者自证，可信度高）

1. `profile.mjs` 的 `dnsRewriteState` 原先读 `profile.rewrite`，而原版调用点是 `rt(n.dns)`——
   **dns.rewrite 整个功能静默失效**；wave-4 fixture 恰好把 rewrite 放在顶层，替错实现打了掩护。
   本实现无此类比 bug：我们的 DNS rewrite 是扁平表（`singbox.py` 直接读 `cfg.dns_rewrites`），不存在嵌套层级读错问题。
2. `shareServers` 必须过 `enabledShares`：只按 protocol 过滤**不看 enabled**，漏了会把用户关掉的分享重新开一个 WAN ACCEPT。

## 五、与我们实现的对照（已在代码里核实）

### 已有（v5 不新增工作）

- `sing-box check -c`：`apply.py` / `service.py` 已在 apply 前校验。
- 部署重试 = 重建：我们的 apply 本就是全量重生成，符合 v5 原则。

### 缺口（v5 给了可直接对标的行为）

1. **启动后验证**：我们 start/restart 后不查内核日志。v5 给出：FATAL 行判定、崩溃/未启动两句话 + 回滚摘要、
   四路判定、降级为纯 tun 的警告文案、迟发崩溃监视。——改动最小、每次部署都受益。
2. **冲突检测**：`service/status` 的 conflictAutoStopped 仍缺（v4 遗留）。v5 preflight 给了冲突判定与
   `conflictMessage`（"检测到 X 正在运行……"）行为，可直接作 Debian 等价实现的参照。
3. **坏节点定位与摘除**：我们只有整配置 check，没有单节点定位。v5 的 `locateFailingOutbound`
   （内核索引/标签 → 节点名 + 订阅名 + 原名）与 `vetOutbounds`（每轮摘一个坏节点；出站索引要 `-1`，endpoint 不要）
   是可借鉴的机制；注意 `badTags` 过滤条件反直觉（定位到 selector 时它自己会被滤掉；完全没定位到时不过滤）。
4. **查询日志闩锁思想**：v5 的"查询日志永不能搞挂部署"（回滚 drop-in + 闩锁 + reason failed）可用于我们的
   dnsmasq query-log 处理（现为固定 conf + 重启，无失败隔离）。

### 不适用（平台/功能分歧，注明即可）

- uci DNS 接管、`/etc/dnsmasq.conf` + `/var/etc/*` 三处 grep、防火墙 uci 段：OpenWrt 专属；我们是 Debian VPS。
- 自签证书：面板无 TLS，不适用。
- 正则→后缀证明器：我们的穿透目前不支持 `domain_regex`（仅 `geodata.py` 有展示名），证明器是未来工具，不是当前缺口。
- deploy-flip 的实现：原版用 `obflip-<sha>` 规则集文件交换实现热切换（flag 文件内容切换 proxy/direct，
  路由段字节不变故无需重启；deploy 全量重写、hot flip 只写 diff）。我们的 selector-now 方案行为等价（热切换无需重启），
  架构不同，无需改。

## 六、建议的下一步（按价值排序，供用户选）

1. **启动验证**（推荐先做）：start/restart 后读 `sing-box.log` 查 FATAL，失败给回滚摘要；降级路径先只做到"报清楚"，不自动降级。
2. 冲突检测：service/status 的 conflicts/conflictAutoStopped Debian 等价实现。
3. 坏节点定位：apply 失败时把内核报错映射到节点名 + 订阅名；vet 式摘除暂缓（需逐出站探测 harness）。

以上三条均为 v5 对照建议，未经用户点头不开工；基线跟进 v0.1.344 之后版本仍按用户决定暂不做。
