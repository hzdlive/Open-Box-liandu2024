# 路由金标准抽查报告（81 测例 vs 穿透逻辑）

> 语料：第三方报告 v3 的 `panel-contract/routing-golden.json`（81 例，生成于 sing-box 1.14.1-openbox-tcp24）。
> 抽查脚本：`oss/tests/test_routing_golden.py`（语料 fixture：`oss/tests/routing-golden.json`）。
> 结论：**可测 38 例全部通过；43 例因穿透模型不支持对应语义而跳过（非失败）。**

## 一、结果

| | 数量 |
|---|---|
| 总测例 | 81 |
| 通过 | 38 |
| 失败 | 0（修复后） |
| 跳过（模型不支持） | 43 |

## 二、发现并修复的真问题（1 个）

**`domain` 精确匹配的大小写语义**（测例 `domain-uppercase-value`）：
- 金标准：规则值 `EXAMPLE.COM`（大写）对目标 `example.com` **不命中**（走兜底 DIRECT）；
- 而 `domain_suffix` 是大小写不敏感的（`WWW.EXAMPLE.COM` 命中 `example.com`）。
- 我们原来的 `_match_domain` 对所有类型都转小写，导致 `domain` 大写值被误判命中。
- 修复：`penetration.py::_match_domain` 改为 `domain` 精确匹配大小写敏感（仅去尾点），`domain_suffix` / `domain_keyword` 保持大小写不敏感。

## 三、跳过分类（43 例，均为已知能力边界）

| 原因 | 例数 | 说明 |
|---|---|---|
| `ip_is_private` | 21 | 穿透模型无私网判定（`ipaddress` 模块可做，暂未接入） |
| `port` / `port_range` | 7 | 穿透输入无端口参数 |
| `rule_set` | 4 | 需规则集展开数据，穿透当前跳过 geosite/ruleset |
| `ip_version` | 3 | 无 IP 版本判定 |
| `domain_regex` | 2 | 无正则匹配 |
| `invert` | 2 | 已知未实现字段（全链路改动大） |
| 多条件 AND | 3 | 单条规则多字段 AND（如 domain_suffix+port），穿透模型为单字段 |
| 无 final 定义 | 1 | 面板恒有兜底出口，不适用 |

## 四、转译方法（可复现）

- sing-box 规则按序转译为前置规则（多值字段展开为多条同出口规则，保持首胜顺序）；
- 期望命中下标之后的规则不影响首胜结果，可忽略；
- 期望命中下标之前的规则若含不支持字段，整例跳过（无法证明其不命中）；
- `action=reject` 转译为 target=reject；兜底测例比对 final 出口。
