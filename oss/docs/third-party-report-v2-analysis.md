# 第三方研究报告 v2 分析：与 v1 的差异及合规评估

> 分析对象：`Open-Box-liandu2024-2.zip`（更新版）
> 对比基线：`Open-Box-liandu2024.zip`（v1，已分析）
> 分析日期：2026-10-19
> 分析人：Muse

---

## 一、版本对比总览

| 维度 | v1 | v2 | 变化 |
|---|---|---|---|
| 大小 | 9.6MB | 19MB | +9.4MB |
| 文件数 | 973 | 1084 | +111 |
| `panel-contract/` | 有 | 有（仅 `contract.json` 微调） | 基本不变 |
| `openbox-panel/` | 有 | 有 | 未对比 |
| 新增顶层文件 | — | 9 个 | 见下表 |

### 新增文件清单

| 文件 | 大小 | 性质 | 可用性 |
|---|---|---|---|
| `open-box-core-reversed.json` | 7KB | **反汇编输出**（capstone disassembly + gosym） | ❌ **不可用**（越过 clean-room 边界） |
| `open-box-windows-reversed.json` | 7KB | **安装包逆向**（NSIS 结构分析） | ❌ **不可用** |
| `open-box-failover-engine.json` | 8KB | 故障转移状态机（state schema + decision reasons） | ⚠️ 谨慎可用（行为事实） |
| `open-box-panel-api-paths.txt` | 2KB | API 路径列表 | ✅ 可用 |
| `open-box-panel-components.txt` | 2KB | 前端组件名列表 | ✅ 可用 |
| `open-box-panel-frontend.json` | 10KB | 前端分析 | ✅ 可用 |
| `open-box-panel-i18n-additions.txt` | 32KB / 1610 行 | i18n key 增补 | ✅ 可用（功能清单） |
| `open-box-rea-report.html` | 375KB | REA 报告英文版 | ℹ️ 这是我们自己的 REA |
| `open-box-rea-report.zh.html` | 372KB | REA 报告中文版（371,996 字节，与我们存档一致） | ℹ️ 这是我们自己的 REA |
| `rea-tools/` | 目录 | 新工具目录 | 待查 |

---

## 二、⚠️ 合规警告：两个 "reversed" 文件不可用

### 2.1 `open-box-core-reversed.json`

其 `_meta` 明确声明：
```json
{
  "artifact": "openbox-core reverse-engineering output",
  "method": "static analysis only (debug/gosym symbol recovery + capstone disassembly)"
}
```

**这是反汇编**（capstone 是反汇编引擎），不是黑盒行为观测。

我们的边界（用户多次确认）：
- ✅ 复刻 UI、API、运行行为、功能语义
- ❌ 禁止复制、反编译、反汇编、恢复闭源实现

**结论**：此文件及其衍生结论**不得用于指导实现**。我们之前依据 REA（黑盒）实现的故障转移状态机不受影响，但不得用此文件去"修正"它。

### 2.2 `open-box-windows-reversed.json`

分析 NSIS 安装包结构（header offset、LZMA 参数等）。同样属于逆向产物，**不可用**。且 Windows 安装包与我们的路由器面板开发无关。

### 2.3 为什么 v1 可用而 v2 部分不可用

- v1 的 `panel-contract/` 是**行为契约**（API 形状、枚举值、测试向量）——可类比"观察到的现象"
- v2 新增的 reversed 文件是**实现还原**（函数映射、反汇编）——属于"复刻实现"

两者有本质区别。我们继续使用 v1 的行为契约 + v2 的行为类新增文件，屏蔽 reversed 文件。

---

## 三、可用新增内容的价值分析

### 3.1 `open-box-panel-i18n-additions.txt`（1610 个 key）⭐ 高价值

这是 v2 最有价值的新增。可作为**功能完整性清单**：

- v1 的 `i18n-en.json` 有 1753 keys
- v2 新增 1610 个"additions"（可能有重叠，需去重）
- 我们四语言 979 keys（+备份 7 keys = 986）

**行动**：将 additions 去重后按前缀聚类，生成"未实现功能清单 v2"，与之前基于 1753 keys 的清单合并。

抽样看到的 key（`backupExport`、`backupImportConfirm`、`activation*` 等）表明覆盖了备份、激活等模块。

### 3.2 `open-box-failover-engine.json`（谨慎可用）

包含：
- `failover_function_map`：函数映射（可能源自符号表——谨慎）
- `state_schema`：持久化状态的字段（行为事实，可用）
- `decision_reasons`：决策原因（行为事实，可用）
- `decision_object`：决策对象结构（行为事实，可用）
- `config_model`：配置模型（行为事实，可用）

**可用部分**：用 `state_schema` 和 `decision_reasons` 交叉验证我们的 `failover_sm.py`（特别是 11 种原因码是否齐全、状态字段是否一致）。

**不可用部分**：`failover_function_map`（函数级映射，属实现细节）。

### 3.3 `open-box-panel-api-paths.txt` + `open-box-panel-components.txt`

纯列表，无实现细节：
- API 路径：可用于核对端点覆盖率（与 openapi.yaml 交叉）
- 组件名：如 `BackupCard`、`ChainProxyEditDialog`、`BlockQuicCard` 等，可推断功能模块是否齐全

**价值**：中等。`BackupCard`、`BlockQuicCard` 等组件名可作为 UI 完整性检查。

### 3.4 `open-box-panel-frontend.json`

10KB，需进一步解析。但基于命名，属前端行为分析，**可用**。

### 3.5 `rea-tools/`

新目录，待检查内容。可能包含测试工具。

---

## 四、与 v1 报告的关系

| 内容 | v1 | v2 | 说明 |
|---|---|---|---|
| panel-contract 行为契约 | ✅ | ✅（基本不变） | 继续作为主要参考 |
| openbox-panel Node 实现 | ✅ | ✅ | 不可用（第三方实现） |
| 故障转移行为 | behavior-spec §5.1 | + failover-engine.json | v2 更细，但需屏蔽实现细节 |
| i18n | 1753 keys | + 1610 additions | v2 更全 |
| 逆向产物 | 无 | 2 个 reversed 文件 | **新增风险，需屏蔽** |

**结论**：v2 = v1 + 更多行为数据 + 两个不可用的逆向文件。**净价值为正**，但需建立防火墙。

---

## 五、建议

### 5.1 建立使用规范

```
✅ 可用：
  - panel-contract/ 全部（行为契约）
  - open-box-panel-i18n-additions.txt（功能清单）
  - open-box-panel-api-paths.txt（端点清单）
  - open-box-panel-components.txt（组件清单）
  - open-box-failover-engine.json 的 state_schema/decision_reasons（行为事实）

❌ 不可用：
  - open-box-core-reversed.json（反汇编）
  - open-box-windows-reversed.json（安装包逆向）
  - open-box-failover-engine.json 的 failover_function_map（函数映射）
  - openbox-panel/ 的 Node.js 代码（第三方实现）
```

### 5.2 立即可做的（基于 v2 新增）

1. **i18n 功能清单 v2**：1610 additions 去重聚类，更新未实现功能列表
2. **故障转移交叉验证**：用 `state_schema`/`decision_reasons` 核对 `failover_sm.py`
3. **组件完整性检查**：用 components.txt 核对管理中心 tab 是否齐全

### 5.3 长期

将本报告与之前的 `third-party-report-analysis.md` 合并为统一的《第三方报告使用指南》，明确可用/不可用边界，供后续开发参考。

---

## 六、总评

v2 报告**可用部分价值高**（i18n additions、failover state schema、API/组件清单），但**混入了两个逆向文件**，使用时必须主动屏蔽。

**评级：B+**（v1 是 A-；v2 内容更多但合规风险更高，拉低评级）

**一句话建议**：取其行为，弃其逆向。i18n additions 立即用，reversed 文件碰都不要碰。
