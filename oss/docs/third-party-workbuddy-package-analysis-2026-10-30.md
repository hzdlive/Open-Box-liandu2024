# 第三方包分析（Open-Box-liandu2024 分卷包，2026-10-30）

总评：**A-（与旧包持平）**。包是旧包 `Open-Box-liandu2024_0_opjx.zip`
的严格超集：删除 0、新增 3293、修改 27。体量增长的大头是
`openbox-panel` 内新 vendored 的依赖与规则集数据（见第二节），契约面
本身只动了一处：core 金语料 +13 例，全部是 configDetailed 的 DNS 方向。
其余契约（端点、失败体、线协议）零变化，上一份报告的结论可直接沿用。

上一份报告：`oss/docs/third-party-workbuddy-package-analysis-2026-10-29.md`
（旧包 697 条目）。本报告只写相对旧包的差异与新结论，不重复旧报告
已覆盖的基线。

## 一、包的构成（3990 条目，解压 448MB，zip 44.6MB）

三段分卷合并验证通过（`testzip` 无损坏）：`.001` 与 `.002` 各 20MiB、
`.003` 约 2.6MB。

| 顶层 | 条目 | 说明 |
|---|---|---|
| openbox-panel | 3646 | 旧包 362；增长见第二节 |
| rea-tools | 109 | +1 新脚本 |
| .tmp | 99 | +7（含 3 份 golden 过程快照） |
| docs | 31 | 全部与旧包相同，无新增 |
| panel-contract | 30 | 仅 core-golden.json 变化 |
| docker | 20 | 不变 |
| .workbuddy-ai | 18 | +1 篇日记，**未读** |
| scripts | 15 | 不变 |
| core-reimpl | 10 | 5 个代码文件 + README + exe 变化 |
| 其他 | 12 | README、PRIVACY、两 reversed JSON 等，不变 |

## 二、与旧包的差异（CRC 对比，文件级）

### 新增 3293：几乎全是 openbox-panel 内的 vendored 内容

- `openbox-panel/node_modules/`（1017 文件，3.0MB，70 个包）：第三方
  Node 依赖原样 vendored，属构建噪音，无分析价值。
- `openbox-panel/open-box/panel/server/`（2197 文件，10.0MB）：其中
  2177 个 `.srs` 文件——sing-box 编译后规则集数据（geoip/geosite
  的二进制形态），余为少量 LICENSE/json/gz/txt/md。属规则集数据，
  不是代码；可作规则集处理时的参考数据，不采纳为实现。
- `openbox-panel/.tmp/`（67 个新增）：探针与测试过程产物（live 快照类，
  未读）。
- `openbox-panel/src/core/policy-entries.mjs`（新代码文件，未读）、
  `openbox-panel/tools/stub-core/stub-core.exe`（2.9MB，未运行）。
- `.tmp/` 3 份 golden 过程快照：`core-golden.before-dns-surface.json`
  （= 旧 golden，35.6MB）、`core-golden.before-dns2.json`（50.5MB）、
  `core-golden.before-static-pick.json`（= 新 golden，53.2MB）——
  过程快照，未读内容，只以文件名确认本次工作主题是 DNS 面。
- `.tmp/deploy/config.live.json` 与 `config.meta.live.json`（live 配置，
  未读）、`.tmp/probe-linux.mjs`（探针脚本，见第四节第 4 条）。
- `rea-tools/check-config.mjs`（新工具脚本，见第四节第 3 条）。
- `.workbuddy-ai/memory/2026-10-30.md`（新日记，**未读**）。

### 修改 27：契约面只动 golden，其余是重实现与过程数据

- `panel-contract/core-golden.json`（35.6MB → 53.2MB）：唯一变化的
  契约文件。核心版本未变（`capturedFrom` 仍是 openbox-core v0.1.337、
  同一 buildID、同一实验机），`_meta` 仅 `caseCount` 212 → 225 与
  `byMethod` 的 configDetailed 25 → 38 两处变化。0 删除、0 修改、
  13 新增，新增全部是 configDetailed（见第四节第 1 条）。
- `core-reimpl/`：`config.go`、`methods.go`、`plans.go`、`routing.go`
  四个代码文件 + `openbox-core.exe` + README 变化（代码未读、不采纳；
  README 方法论见第四节第 2 条）。
- `openbox-panel/src/` 6 个代码文件变化（kernel-start、route-oracle、
  backup、client、index、paths，未读）与 README 增长（277KB → 281KB）、
  `test/panel-wave5-live-diff.mjs` 变化（测试脚本，未读内容）。
- `openbox-panel/.tmp/live-diff/` 数据更新（sqlite、live-state.json、
  diff-report.md，live 快照，**未读**）；`.tmp/answers-r1.jsonl`
  增长（26MB → 39MB，未读）。
- `rea-tools/core-cases.mjs`、`diff-live-store.mjs` 变化（工具更新）。
- `.workbuddy-ai/memory/MEMORY.md`（33KB → 11KB，重写）与 TRAPS.md
  增长，**未读**。

### 未变（可直接沿用旧结论）

- `panel-contract/` 其余 29 个文件全程未变：`contract.json`、
  `openapi.yaml`（122 端点 / 81 路径）、`fail-shapes.json`、
  `core-protocol.json`（28 例）、`behavior-spec.md` 均与旧包 CRC 一致。
  上一份报告的错误形 parity 结论与订阅 10mb、分享删除待核对项均不受影响。
- `docs/` 全部文件未变。
- 两份 reversed JSON 与旧包 **MD5 完全相同**（仅哈希比对，未读内容）：
  `open-box-core-reversed.json` = `48fe1849e8bcbab1db4373a4edbc0c0d`、
  `open-box-windows-reversed.json` = `2cf4a789916194e1afd8ccb85dc47175`，
  继续屏蔽。

## 三、来源分级（沿用旧报告分级，新增项归位）

- **可用（行为契约与方法论）**：新 golden 的 13 个 configDetailed DNS
  例（见第四节第 1 条）、reimpl README 的方法论自述、
  `rea-tools/check-config.mjs` 与 `.tmp/probe-linux.mjs` 的方法论、
  `open-box/panel/server/` 的 `.srs` 规则集数据（参考数据）。
- **仅行为对照，不复制**：`openbox-panel` Node 代码（含新增的
  policy-entries.mjs）、`core-reimpl` Go 代码与两个 `.exe`
  （stub-core.exe 新增，同样不运行、不采纳）。
- **屏蔽（未读、未引用、未落档）**：两份 reversed JSON；
  `.workbuddy-ai/` 全部（含新日记 2026-10-30 与重写的 MEMORY.md）；
  `.tmp` 与 `openbox-panel/.tmp` 的 live 快照类（sqlite、live-state、
  deploy live 配置、answers-r1、before-*.json 过程快照、test 日志）；
  `panel-contract/core-golden.json` 本体（只经 harness 程序化比对，
  不读、不打印、不复述其值）。

## 四、对 oss 最有价值的线索（按价值排序，全部待黑盒复核）

### 1. Golden +13 例：configDetailed 的 DNS 面（本包唯一契约增量）

新增 13 例的 id（仅 id，不含值）：
`dns-autoRedirect-off`、`dns-autoRedirect-off-split-off`、
`dns-autoRedirect-off-bypass-off`、`dns-autoRedirect-off-bypass-sets`、
`dns-autoRedirect-off-bypass-flag-off`、
`dns-autoRedirect-off-bypass-flag-on-empty`、`dns-bypass-off`、
`dns-bypass-sets`、`dns-rewrite-off`、`dns-hijack-off`、`dns-fakeip-off`、
`dns-static-pick`、`dns-static-pick-fakeip-off`。

命名规律是“一次关一个 DNS 开关”（autoRedirect、bypass、rewrite、
hijack、fakeip、static-pick），与旧 25 例的 probe 命名一脉相承。
对 oss 的意义：configDetailed 是我方 core 复刻最后一项未实现的方法
（25 例 → 38 例），这 13 例直接划定了其 DNS 一节的覆盖范围——实现
configDetailed 时须以这 38 例为准绳，而非旧 25 例。13 例的取值细节
留待实现时以 harness 逐例对，不在本报告展开。

### 2. 我方已实现方法不受影响：新 golden 下 155/155 仍全过

新 golden 中 0 例修改、0 例删除，故已实现的 10 个方法理应全过；
已用新 golden 实测复核（程序化比对，只计通过数）：
normalizeRouting 8、normalizeGroups 9、normalizePolicy 2、
normalizeCustom 2、builtinTags 2、emitGroups 121、classes 2、
entryPlan 3、bypassPlan 3、forwardPlan 3，合计 **155/155**。
另：reimpl README 新增的 failover 一节自述的规则（lane 按可解析
成员数分 empty/single/urltest、lane id 一位编号、interval 窗口
[5s, 86400s] 加挽救解析）与我方独立推导的 emitGroups 规则一致，
属方法论级旁证，不采纳其代码。

### 3. check-config 方法论：字节相等 ≠ 配置有效

新工具 `check-config.mjs` 的思路是：把生成的配置交给真实内核
`sing-box check`（同款 1.14.1-openbox 构建）验收。理由是两实现
字节相等只证明彼此同意，不证明产物能被内核接受（字段被新版
改名、rule_set 指向内核不支持的格式等问题在 diff 中存活）。
对 oss 的建议：实现 configDetailed 后，除 harness 比对金语料外，
加一道 `sing-box check` 验收生成配置——这是方法论采纳，不是代码采纳。

### 4. probe-linux 方法论：client-config 路由已进入探针范围

新探针 `probe-linux.mjs` 以 live-state 种子库 + 真实核心启动面板，
探针目标是 `/api/openbox/defaults/routing` 与两条 client-config 路由。
与 oss 的关系：客户端协议面仍在暂缓（无客户端 App 配对），本条仅
记录“第三方已开始探针 client-config”，不产生 oss 动作。

### 5. 契约面稳定：上一份报告的待核对项原样保留

端点、失败体、线协议零变化，故：错误形 parity 结论不变；订阅
10mb 微缺口不变；分享删除“再删 200 vs 未知 404”仍需原版黑盒核对
（会动原版数据，须用户另批），本包未提供新证据。

## 五、诚实缺口与风险

- 本报告未读清单见第三节屏蔽项；未读文件的内容一律未引用、未复述。
- 新 golden 的 13 个 DNS 例只做了 id 与主题归类，未逐例分析取值；
  其取值留待 configDetailed 实现时以 harness 对。
- `.srs` 规则集数据只做了计数与格式归类，未逐条解析内容。
- 两 reversed JSON 与旧包 MD5 相同，继续按 clean-room 边界屏蔽；
  与黑盒实测冲突时以实测为准（本报告无此冲突）。
- 本报告不改 oss 代码；第四节各条进入实现前，均须按既定规则经黑盒复核。
- 复现方法：三段分卷按序拼接后以 zip 内 CRC 对比新旧包（同名 CRC 变
  即修改，新增即超集），再按第三节排除表解压后分析；排除表外的文件
  均未纳入结论。
