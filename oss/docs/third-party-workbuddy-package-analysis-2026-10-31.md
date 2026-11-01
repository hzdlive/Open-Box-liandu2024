# 第三方包分析（Open-Box-liandu2024 分卷包，2026-10-31）

总评：**A-（与 10-30 持平）**。包是 10-30 包的严格超集：删除 0、
新增 99 文件、修改 35 文件。契约面第一次动了金语料之外的文件
（contract、fail-shapes、openapi、write-shapes 四个），但变化主题
单一：第三方捕获主机上 core 跑起来了（openbox-core.exe），原来因
core 不可用而产生的 500 占位被真实答案取代；另有两处静态分析修正。
金语料 225 例零变化，core 复刻结论（含 routingFingerprint 收束）
不受影响。

上一份报告：`oss/docs/third-party-workbuddy-package-analysis-2026-10-30.md`
（旧包 3990 条目）。本报告只写相对旧包的差异与新结论，不重复旧报告
已覆盖的基线。

## 一、包的构成（4109 条目，解压 464MiB，zip 48.3MB）

三段分卷合并验证通过（`testzip` 无损坏）：`.001` 与 `.002` 各 20MiB、
`.003` 约 6.1MB。

| 顶层 | 条目 | 相对 10-30 | 说明 |
|---|---|---|---|
| openbox-panel | 3723 | +77 | 见第二节 |
| .tmp | 140 | +41 | 见第二节 |
| rea-tools | 109 | 0（4 改） | 工具更新，与 write/fail 重捕配套 |
| docs | 31 | 0 | 全部与旧包相同 |
| panel-contract | 30 | 0（4 改） | 见第三节 |
| docker | 20 | 0 | 不变 |
| .workbuddy-ai | 19 | +1 | 新日记一篇，**未读** |
| scripts | 15 | 0 | 不变 |
| core-reimpl | 10 | 0（3 改） | README、methods.go、exe 变化（未读） |
| 其他 | 12 | 0 | README、PRIVACY、两 reversed JSON 等，不变 |

## 二、与旧包的差异（CRC 对比，文件级）

### 新增 99：探针产物 + 一个全新的 flip 目录 + .tmp 快照

- `openbox-panel/.tmp/wave47/`、`wave48/` 探针产物（sqlite 快照、
  e2e 数据、探针脚本，live 数据，**未读**）。
- `openbox-panel/open-box/data/flip/` 全新目录（26 文件，仅记名，
  **未读内容**）：12 个 `obflip-*.json`（其中 4 个哈希与金语料已知
  策略一致：Speed、AI、TikTok、Apple；另 8 个新哈希）、10 个
  `obflip-byp-geoip-*.srs`、fallback、need-all、placeholder。
  它们是生成输出，不是哈希算法证据——configDetailed 的 flip 哈希
  缺口状态不变。
- `openbox-panel/open-box/etc/config.candidate.json` 与 `meta.json`
  （live 候选配置，**未读**）。
- `openbox-panel/src/core/kernel-stale.mjs`（新代码文件，未读）、
  `openbox-panel/test/panel-wave5-*.mjs` ×3（latency-anchor、
  kernel-stale、core-presence，未读）。
- `.tmp/` 39 个：before-/after- API 快照（activation、license、
  client-config、config_preview、policies Speed 条目，live 数据，
  **未读**）；探针脚本 `*.mjs`（align-tables、inspect-db、list-keys、
  patch-filter、probe-cc、probe-cc2、probe-ruleindex、read-auth、
  seed-orig、smoke，仅记文件名）；`core-buildid.conf`（drop-in
  构建元数据，见第四节第 2 条）；`lab-diff-report.md`（仅读标题，
  见第四节第 3 条）；`router-cookies.txt`、`router-login.json`
  （路由器认证材料，**严禁读**）；`o2026/`、`o2027/` bundle
  （**未读**）；`openbox-core-linux-amd64`（第三方二进制，哈希与
  VPS 原版不同，**未运行**，见第四节第 2 条）。
- `.workbuddy-ai/memory/2026-10-31.md`（新日记，**未读**）。

### 修改 35：契约 4 个 + 代码与过程数据

- `panel-contract/` 4 个（见第三节）。
- `openbox-panel/` 21 个：README、package.json、
  `src/core/deploy-run.mjs`、`deploy-service.mjs`、
  `latency-history.mjs`、`src/generated/routes.gen.mjs`、
  `src/index.mjs`（代码，未读）、wave5 测试 3 个（deploy-run、
  live-diff、openapi-sync，未读）、`.tmp/live-diff/` 过程数据
  （sqlite、diff-report，live 快照，**未读**）。
- `rea-tools/` 4 个：`apply-write-shapes.mjs`、
  `capture-fail-shapes.mjs`、`capture-write-shapes.mjs`、
  `diff-live-store.mjs`（工具更新，与下节重捕配套）。
- `core-reimpl/` 3 个：README、`methods.go`、`openbox-core.exe`
  （代码与 exe，未读、不采纳）。
- `.workbuddy-ai/memory/` 3 个：MEMORY.md、TRAPS.md、
  2026-10-29.md（**未读**）。

### 未变（可直接沿用旧结论）

- `panel-contract/core-golden.json` CRC 一致：仍 225 例、19 方法、
  核心版本 v0.1.337 同 buildID——金语料零变化。
- `docs/`、`docker/`、`scripts/` 全部文件未变。
- `openapi.yaml` 路径与操作数未变（122 操作），+960B 在描述性内容。
- 两份 reversed JSON 与旧包 **MD5 完全相同**（仅哈希比对，未读内容）：
  `open-box-core-reversed.json` = `48fe1849e8bcbab1db4373a4edbc0c0d`、
  `open-box-windows-reversed.json` = `2cf4a789916194e1afd8ccb85dc47175`，
  继续屏蔽。

## 三、契约面变化详解（本包唯一值得展开的部分）

### 主题：捕获主机上 core 跑起来了，500 占位被真实答案取代

- `fail-shapes.json`（重捕于 2026-10-31，failureObservations
  94 → 88，host 新增 `openbox-core.exe`）：原来“原生核心无法运行”
  的 500 占位被取代——activation/license 的 GET/DELETE → 200 真实
  分支；`config/preview` → 200 真实配置；POST/PUT activation → 400
  真实校验（invalid activation code / not activated）；PUT profile/
  → 200；PUT groups 在 contract 侧的 error 键被移除。
- `write-shapes.json`（合并双主机捕获，`merged: true`，旧主机 +
  `openbox-core.exe`；core-unavailable 9 → 0，ok 30 → 34，rejected
  12 → 15）：路由 id 归一化为 `:id` 占位（纯整理）；`_meta`
  新增 disagreements 1 条：DELETE subscriptions/:id 的 `applied` 键
  两主机不一致（core 主机有，旧主机无）——`applied` 是否出现与
  主机/状态有关，不能照抄任一。
- `contract.json`（端点数仍 122；corrections 15 → 17，两条静态
  分析修正：write 路由 response.keys 改为实测、response.status 跨对
  reconciled）：DELETE activation 成功键
  [activated, defaults, left, right]；DELETE license 成功键
  [license, permissions]；POST activation 状态新增 400；POST deploy
  状态新增 503；PUT groups 成功键去掉 error；PUT profile/ 成功键
  error → applied；DELETE subscriptions/:id 成功键新增 applied
  （与 disagreements 呼应）。
- 版本漂移注：fail-shapes 观测到的原版最新版为 v0.1.382
  （2026-10-31）；我方对标基线仍是用户定的 v0.1.341，不跟进。

### 对 oss 的核对结果（已实测我方代码，不是空泛“待核对”）

- PUT /api/openbox/groups、PUT /api/openbox/profile/：我方无此二
  /api/openbox 路由（组走 /api/groups 原生路由），契约变化无 oss
  动作，不是缺口。
- POST /api/openbox/deploy 503：我方 deploy.py 已有 503 映射，但触发
  条件是 rulesets 阶段失败；新文档的 503 触发是部署时内核/网络
  不可达——触发条件不同，我方该分支是否覆盖需黑盒核对（未证明
  缺口，仅标记）。
- DELETE subscriptions/:id 的 `applied`：两主机本身不一致，照抄任一
  都是错的；以黑盒实测为准，暂不改我方实现。
- 激活/许可类（activation、license 的 DELETE/POST/PUT）：范围外
  （许可类排除），无 oss 动作。
- 分享删除（升级报告第 4 项）：新包仍无“删不存在分享”的用例，
  仍需用户另批原版黑盒核对，本包未提供新证据。

## 四、其他线索（按价值排序，全部待黑盒复核）

### 1. 金语料零变化 → core 复刻结论全部站立

13 法 + hello 的实现与金语料覆盖不变；routingFingerprint 收束结论
（字段集闭合、序列化未破、保持明确报错的未实现）不受影响，
因无新增指纹例。

### 2. reimpl 的 buildID 门（方法论注记，不采纳做法）

`.tmp/core-buildid.conf` 自述：面板拿 `hello.buildID` 对编译期常量，
不一致即报错，因此 drop-in 须声明所替版本。`.tmp/` 的 core 二进制
哈希与 VPS 原版不同（且体积 2.4MB vs 原版 3.66MB），应是第三方
reimpl 的 drop-in 产物而非原版证据——未运行、未用作证据。我方
hello 刻意不冒充原版 buildID 的路线不变。

### 3. 第三方在做读路由的 live differential

`.tmp/lab-diff-report.md` 仅读标题：主题是 store-backed 读路由的
live differential，两节标题为 “Not seedable” 与 “Dropped at any
depth”；与 wave47/wave48 探针产物呼应。正文未读，不引用其结论。

### 4. .tmp before-/after- 快照的主题

activation、license、client-config、config_preview 的前后对比——
第三方在探针许可与客户端配置面；客户端协议面我方仍暂缓，不产生
动作。

## 五、来源分级（沿用旧报告分级，新增项归位）

- **可用（行为契约与方法论）**：本节第三节的契约 diff（键/状态级）、
  reimpl buildID 门的方法论自述、lab-diff-report 的标题级主题。
- **仅行为对照，不复制**：`openbox-panel` Node 代码（含新增的
  kernel-stale.mjs）、`core-reimpl` Go 代码与 exe、`.tmp/` 的 core
  二进制（未运行）。
- **屏蔽（未读、未引用、未落档）**：两份 reversed JSON；
  `.workbuddy-ai/` 全部（含新日记 2026-10-31）；`.tmp` 与
  `openbox-panel/.tmp` 的 live 快照类（sqlite、before-/after- API
  快照、bundle、live-diff 过程数据、路由器认证材料）；flip 生成物
  内容；`panel-contract/core-golden.json` 本体（只核对 `_meta` 与
  CRC，不读、不打印、不复述其值）。

## 六、诚实缺口与风险

- 本报告未读清单见第五节屏蔽项；未读文件的内容一律未引用、未复述。
- 契约 diff 只做到键/状态/计数级；openapi 描述性增量未逐字比对；
  fail-shapes 的 excerpt 值一律未引用（部分含 live 数据）。
- flip 生成物只做了文件名与哈希归类，未解析内容；新 flip 哈希不
  构成哈希算法的新证据。
- 两 reversed JSON 与旧包 MD5 相同，继续按 clean-room 边界屏蔽；
  与黑盒实测冲突时以实测为准（本报告无此冲突）。
- 本报告不改 oss 代码；第三节标记的 deploy 503 触发核对须黑盒复核
  后才动。
- 复现方法：三段分卷按序拼接后以 zip 内 CRC 对比新旧包（同名 CRC
  变即修改，新增即超集），再按第五节排除表分析；排除表外的文件
  均未纳入结论。
