# OSS 升级报告（依据：第三方包分析 2026-10-29）

依据：`oss/docs/third-party-workbuddy-package-analysis-2026-10-29.md`
（新包 `Open-Box-liandu2024_0_opjx.zip`）+ 2026-10-29 对 OSS 现状的核实。
**本报告本身不改任何代码；实施需逐项点头。**

## 一、总览

| # | 升级项 | 类型 | 优先级 | 风险 | 状态 |
|---|---|---|---|---|---|
| 1 | 错误形 parity 测试（fail-shapes） | 新增测试 | 高 | 无（只加测试） | 待点头 |
| 2 | 状态码 parity 测试（contract/openapi 补全） | 新增测试 | 高 | 无（只加测试） | 待点头 |
| 3 | 订阅路由 body 上限 1mb → 10mb | 单点对齐 | 低 | 极低（只放宽） | 待点头 |
| 4 | 分享删除语义核对（再删 200 vs 404） | 黑盒核对 | 待批 | 需动原版数据 | **阻塞，需用户另批** |
| — | core-protocol、core-reimpl、鉴权形态、client/* | 不升级 | — | — | 见第四节 |

先说一个好消息：我方错误形已经与实测吻合。现行代码错误体清一色
`{"error": ...}`（"not found" 50 处、`str(e)` 28 处等），没有任何一处发
`{code, error, message}` 并集；404 处理分两层——handler 内 abort(404) 回
JSON `{"error": "not found"}`，未匹配路径回 Express 风格 HTML 页——与原版
结构一致。所以第 1、2 项是**验证**，预期缺口很少，不是修复。

## 二、逐项说明

### 1. 错误形 parity 测试（fail-shapes.json，122 路由）

- **证据**：新包 fail-shapes.json 对 122 路由实测了“请求写错时面板说什么”：
  失败体主形态是单个 `error`（68 次），`message` 25 次，`code` 仅 2 次
  （auth 改密 401）；旧 openapi 的 `{code, error, message}` 并集是错的。
- **我方现状**：错误体已是 `{"error": ...}` 主形态（已核实，无 `code` 并集）；
  但从未系统比对过 122 路由。
- **可测交集**：我方 220 条（方法+路径）与 fail-shapes 122 条的交集为
  **28 对**，对应 23 条 `/api/openbox/*` 路径：
  content-filter（GET/DELETE/PATCH）、deploy、deploy/state、diagnostics、
  dns/flush-cache、dns/region-detect、failover/recheck、failover/status、
  penetration、route-test、subscription-shares（列表/单条/regenerate）、
  subscriptions/order、subscriptions/preview、terminal-test、
  terminal-test/capability。
- **做法**：新增测试文件，载入 fail-shapes.json，对上述 28 对断言我方
  错误体的键集合与原版一致；**排除**鉴权门 403（`PASSWORD_SETUP_REQUIRED`，
  我方无鉴权设计）与 auth 路由“错请求仍回 200”的情形。
- **产出**：缺口清单（若有），缺口修复另案，不在本项内改行为。

### 2. 状态码 parity 测试（contract.json / openapi.yaml 状态补全）

- **证据**：新版 contract/openapi 把旧版 49 条 `[]` 与 44 条缺 200 补齐；
  端点与路径数量零变化（122 端点、81 路径），响应键集合全程未变。
- **我方现状**：未系统比对过状态码。
- **做法**：与第 1 项同一测试文件（或相邻文件），对上述 28 对断言我方
  返回的状态码落在原版补全后的集合内；**排除** 401/403（鉴权门，不适用）。
- **产出**：状态码缺口清单（若有），修复另案。

### 3. 订阅路由 body 上限 1mb → 10mb（单点对齐）

- **证据**：新 `_meta.corrections` 称 subscriptions 路由挂
  `express.json({limit:"10mb"})`（7 条路由）。
- **我方现状**：`panel/app.py` 约 435–465 行：`/api/*` 统一 1mb、
  备份导入 32mb、仅按 Content-Length 门控；订阅路由无单独上限。
- **做法**：给订阅路由加 10mb 例外（与备份 32mb 同机制），附一个合成
  大体请求测试（>1mb 体不再被拒）。
- **影响评估**：订阅请求体实务中只是 URL，几乎触不到 1mb；此项纯为
  保真，优先级低，可与第 1、2 项同批做。

### 4. 分享删除语义核对（阻塞，需用户另批原版黑盒）

- **事实**：新版 contract 仍给 `DELETE /api/openbox/subscription-shares/:id`
  列出 404；同期 write-shapes 重捕意图却写“再删回 200；DELETE 永不 404”。
- **我方现状**：`/api/openbox/*` 两条删除（content-filter、subscription-shares）
  本就是无条件删除、永不 404，与重捕吻合；`/api/subscription-shares`
  （新路径）对未知 id 回 404。
- **为什么不能直接改**：“从未存在”→404 与“已删过”→200 能否调和，
  产物里判定不了；核对要在原版面板上建、删、再删一个分享——**会动原版
  数据**，须用户另批。在此之前不改任何删除语义。

## 三、交集之外的 63 条与 12 条（说明，不产生任务）

- fail-shapes 有、我方无的 63 条 `/api/openbox/*` 路由中，约一半在我方
  `/api/*`（无 openbox 前缀）下有对应实现（traffic、groups、subscriptions、
  dns-filter、node-info、site-latency、latency-history、rulesets、
  system/timezone、service、backup、update 等，路径前缀不同而已）；
  其余属已明确排除的范围（鉴权/激活/许可/客户端面、出厂重置、教程视频）
  或已知 backlog（回滚、policies 模型）。不因此新增功能项。
- 我方有、fail-shapes 无的 12 条 `/api/openbox/*` 路径（clash-* 转发、
  content-filter preset/restore/refresh、entry-plan、final-select、
  proxy-settings、selection-sync）是我方自有扩展，原版无对照物，
  不纳入 parity 测试。

## 四、不升级项与理由

- **core-protocol.json（28 例）**：核心进程边界契约；我方无 openbox-core
  组件（配置组装在 `singbox.py`），不适用，仅存档。
- **core-reimpl（Go 代码 + exe）**：第三方代码与 built 二进制，按规则不采纳；
  且 core 组件本身不在复刻范围。
- **鉴权形态**（403 `PASSWORD_SETUP_REQUIRED`、auth 路由 200 体）：我方无
  鉴权设计（不做假鉴权），全部排除。
- **client/*、sub/*、activation、license、factory-reset、tutorial-videos**：
  客户端面暂缓 / 排除范围，不动。
- **.tmp 捕获输出与 core-golden.json**：按分析报告边界未读，不进入任何结论。

## 五、建议实施顺序

1. 第 1 项（错误形 parity 测试）——先做，零行为风险，产出缺口清单。
2. 第 2 项（状态码 parity 测试）——与第 1 项同批，同一测试文件。
3. 第 3 项（订阅 10mb 对齐）——单点改动，可与测试同批部署（纯后端，
   无需 Ctrl+F5；部署前按惯例跑全量测试）。
4. 第 4 项——用户批了原版黑盒核对后再定；批之前不碰删除语义。

## 六、诚实声明

- 本报告的每一项“证据”均来自分析报告与 2026-10-29 的现状核实
  （路由交集 28 对、错误体形态、body 上限代码位置、删除语义均已实测），
  未凭空增补。
- 第 1、2 项即使全过，也只证明 28 对交集的错误形与状态码与原版一致，
  不证明全部 122 路由（其余 94 条或无我方实现、或属排除范围）。
- 第 4 项在用户批准前无结论；本报告不把“再删 200”或“未知 404”
  任一说法当作已证实。
