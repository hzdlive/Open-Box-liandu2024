# 第三方包分析（Open-Box-liandu2024_0_opjx.zip，2026-10-29）

总评：**A-（与旧包持平）**。包是旧包 `Open-Box-liandu2024_0_9kbp.zip` 的严格超集：
删除 0、新增 126、修改 19。可用的增量集中在三处：wave5 失败路径契约、
`response.status` 补全、core 线协议契约；体量增长的大头（`.tmp` 捕获输出、
35MB core 金语料）按边界未读、不采用。

上一份报告：`oss/docs/third-party-workbuddy-package-analysis.md`（旧包 571 条目）。
本报告只写相对旧包的差异与新结论，不重复旧报告已覆盖的基线。

## 一、包的构成（697 条目，解压 271MB，zip 21.4MB）

| 顶层 | 条目 | 说明 |
|---|---|---|
| openbox-panel | 362 | 第三方 Node 重实现（仅行为对照，不复制） |
| rea-tools | 108 | 分析员自研工具脚本（方法论可用） |
| .tmp | 92 | 探针脚本与捕获夹具（见第三节分级） |
| docs | 31 | 全部与旧包相同，无新增 |
| panel-contract | 30 | 行为契约（本报告重点） |
| docker | 20 | 部署相关 |
| .workbuddy-ai | 17 | 分析员工作记忆，含 live 信息，**未读** |
| scripts | 15 | 部署脚本 |
| core-reimpl | 10 | 新增：第三方 Go 核心重实现（见第四节） |
| 其他 | 12 | README、PRIVACY、两 reversed JSON、failover-engine 等 |

## 二、与旧包的差异（CRC 对比，文件级）

### 新增 126

- `.tmp/` 探针脚本与夹具（全新目录）：`probe-*.mjs`（failover×9、chain×4、
  forward、license、protocol、variants、entry、dynamic、classes、bypass、
  order-lanes、methods）、`probe/*.json` 捕获输出（未读，见第三节）、
  `core-golden.before-*.json`（35MB/8MB/4MB，未读）、`answers-r1.jsonl`
  （26MB，未读）、`fp/`（疑似逆向工具链，含 `objdis.py`，未读）、
  `goparse/`、`core337/server.tgz`（未读）、`openbox.sqlite`（live 快照，
  未读）、`cookies.txt`（会话凭证，**未读**）、`ssh/askpass.sh`（未读）。
- `core-reimpl/`：Go 核心重实现（config/methods/plans/routing/main/util、
  go.mod、README）+  built 产物 `openbox-core.exe`（3.6MB，未运行）。
- `panel-contract/` 3 个新文件：`core-golden.json`（35MB，未读）、
  `core-protocol.json`（28 例，见第四节）、`fail-shapes.json`（122 路由，
  见第四节）。
- `rea-tools/` 9 个新脚本：core-capture、core-cases、core-diff、core-oracle、
  core-protocol、core-section-diff、capture-fail-shapes、apply-fail-shapes、
  reconcile-status（方法论，见第四节）。
- `openbox-panel/test/` 2 个 wave5 脚本：panel-wave5-fail-shapes、
  panel-wave5-status-sync；另有 `.tmp/`（reimpl-db、test-all.log、reimpl.log，
  其中 db 与 log 含 live 数据，未读）。
- `.workbuddy-ai/memory/` 新增 2 篇日记（2026-10-28、2026-10-29），**未读**。

### 修改 19

- `panel-contract/contract.json`（80KB→95KB）：端点清单不变（122 个），
  唯一变化是 `response.status` 补全——旧版 49 条为 `[]`（“此路由不回答”）、
  44 条缺 200，新版系统补上 200/401/403 及适用的 400/404/500/503；
  响应键集合全程未变。`_meta.corrections` 新增：groups 路由 1mb 勘误补完、
  subscriptions 路由 10mb 新勘误（见第四节）。
- `panel-contract/openapi.yaml`（444KB→461KB）：路径 81、操作 122，数量与旧版
  完全相同；增长同样来自状态与错误响应补全，无新端点。
- `panel-contract/write-shapes.json`（同大小、CRC 变）：仅 `capturedAt`
  更新为 2026-10-28 与重捕 ID 更换，无新形态；但重捕意图值得注意
  （见第四节第 4 条）。
- `openbox-panel` README（252KB→277KB）、package.json、3 个 wave5 测试脚本、
  `rea-tools/diff-live-store.mjs`、`sync-openapi.mjs`（工具更新）。
- `.workbuddy-ai/memory/` 3 篇修改（MEMORY、TRAPS、2026-10-27），**未读**。
- `openbox-panel/.tmp/live-diff/` 快照（sqlite、live-state.json）更新，**未读**。

### 未变（可直接沿用旧结论）

- `panel-contract/behavior-spec.md`、路由/端点清单、docs/ 全部文件。
- 两份 reversed JSON 与旧包 **MD5 完全相同**：
  `open-box-core-reversed.json` = `48fe1849e8bcbab1db4373a4edbc0c0d`（6955 字节）、
  `open-box-windows-reversed.json` = `2cf4a789916194e1afd8ccb85dc47175`
  （6923 字节），继续屏蔽。

## 三、来源分级（沿用旧报告分级，新增项归位）

- **可用（行为契约与方法论）**：`panel-contract/fail-shapes.json`、
  `core-protocol.json`、contract/openapi 的状态补全、rea-tools 新脚本、
  `.tmp` 探针 `.mjs` 脚本（只读方法论，不读其捕获输出）。
- **仅行为对照，不复制**：`openbox-panel` Node 代码、`core-reimpl` Go 代码与
  `.exe`（见第四节第 6 条）。
- **屏蔽（未读、未引用、未落档）**：两份 reversed JSON；
  `.workbuddy-ai/` 全部；`.tmp` live 快照类（openbox.sqlite、cookies.txt、
  core337/server.tgz、probe/*.json、answers*.jsonl、core-golden*.json、
  reimpl-db、live-diff 数据、ssh/askpass.sh）；`.tmp/fp/`（疑似逆向工具链）；
  `panel-contract/core-golden.json`（35MB 配置倾倒，可能含 live 凭据）；
  `openbox-panel/.tmp/live-diff/diff-report.md` 与 test-all.log（live 摘要与日志）。

## 四、对 oss 最有价值的线索（按价值排序，全部待黑盒复核）

### 1. fail-shapes.json：122 路由的真实失败体（本包最大可用增量）

这是分析员 wave5 的工作：前三波只测了成功路径，wave5 补测“请求写错时
面板说什么”。对 122 路由的失败观测计数：200 占 60（错请求仍回 200 的
路由，如 auth 类）、400 占 54、404 占 27、500 占 10、401 占 2、503 占 1。
错误键分布：`error` 68 次、`message` 25 次、`code` 仅 2 次（auth 改密 401）。
结论与旧 openapi 直接冲突：旧 openapi 给全部 87 个错误响应贴了统一的
`{code, error, message}` 并集——实测面板从不同时发这三个键，主形态就是
单个 `error`。我方现行 `{"error": ...}` 主形态与此吻合；后续可据此做一次
错误形 parity 抽查，而不是改代码。另：403 鉴权门
（`PASSWORD_SETUP_REQUIRED`，覆盖 104 路由、reimpl 全同意）属鉴权层，
我方无鉴权设计，不适用。

### 2. response.status 补全：清单稳定，错误码可核对

端点与路径数量零变化，补全只影响状态码集合。401/403 属鉴权门（不适用）；
200/400/404/500/503 的补全可用于核对我方各端点的错误码是否与原版一致，
属测试向量级价值，不直接产生新功能。

### 3. 订阅路由 body 10mb 新勘误（微缺口，实务影响极小）

新 `_meta.corrections` 称 subscriptions 路由挂 `express.json({limit:"10mb"})`
（index.mjs:9826-9831，7 条路由）。我方现行 `/api/*` 统一 1mb（④ body limit），
订阅路由上与原版差 10 倍。但订阅请求体实务中只是 URL，几乎不可能触及
1mb 上限，记为微缺口，不建议为此单独改动。

### 4. write-shapes 重捕：无新形态，但留下一个 404/200 待核对项

重捕只换了时间戳与 ID，无新形态。但其意图写明：content-filter 删除与
分享删除“再删回 200；DELETE 永不 404”。与 contract 并存的另一事实是：
新版 contract 仍给 `DELETE /api/openbox/subscription-shares/:id` 列出 404。
我方现状：`/api/openbox/*` 两条删除（content-filter、subscription-shares）
本就是无条件删除、永不 404，与重捕吻合；`/api/subscription-shares`（新路径）
对未知 id 回 404。两者能否调和（“从未存在”→404 vs“已删过”→200）无法
从产物判定，需原版黑盒核对——且该核对会动原版数据，须用户另批，
本报告不猜结论。

### 5. core-protocol.json：28 例核心线协议失败体（存档，不适用）

核心进程边界（stdin 一行 JSON → stdout 一行 JSON，`protocol:1`）的失败
路径：空输入、空白、非 JSON、数组、args 非数组、protocol 为字符串/浮点、
license 为数字等，统一回 `{error:"invalid native-core request", ok:false,
protocol:1}`，exit 0；并注明“尾部数据先于协议检查、两者都在首次解码后
检查”。方法论干净，但我方不走 openbox-core 协议（无此组件，配置组装在
`singbox.py`），故仅存档，不进实现。

### 6. core-reimpl：方法论可信，代码与二进制不采纳，且不在复刻范围

README 自述方法论是黑盒 oracle：以真实核心为 oracle 跑两轮输入矩阵
（round 1 产出 round 2 依赖的 `builtin`/`members`），金语料 120/120、
19 方法全 exact、协议 28/28；自称“无一字源于原版代码，边界即全部接口”。
即使该自述属实，按既定规则仍不采纳第三方代码与 built 二进制；且 core
组件本身不在 oss 复刻范围（我方不等价物是 `singbox.py` + `deploy.py`，
不是 openbox-core 替代品）。其金语料 `core-golden.json`（35MB）未开
（体量 + 可能含 live 凭据），只可经其 diff 工具间接使用。

### 7. .tmp 探针脚本：方法论参考

探针主题覆盖 failover、chain、forward、license、protocol、variants、entry、
dynamic、classes、bypass、order-lanes 及 lists/selectors/policies 夹具。
只读脚本方法论，不读其捕获输出；对 oss 的直接价值低于第 1、2 条。

## 五、诚实缺口与风险

- 本报告未读清单见第三节屏蔽项；未读文件的内容一律未引用、未复述。
- fail-shapes 只做了结构与计数分析，未逐条比对我方各端点；订阅 10mb、
  分享再删 404/200 均未黑盒核对；core-golden 35MB 未开。
- 两 reversed JSON 与旧包 MD5 相同，继续按 clean-room 边界屏蔽；
  与黑盒实测冲突时以实测为准（本报告无此冲突）。
- 本报告不改 oss 代码；第四节各条进入实现前，均须按既定规则经黑盒复核。
- 复现方法：以 zip 内 CRC 对比新旧包（同名 CRC 变即修改，新增即超集），
  再按第三节排除表解压后分析；排除表外的文件均未纳入结论。
