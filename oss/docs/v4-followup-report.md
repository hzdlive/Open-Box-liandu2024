# v4 对标实施：入口旁路 2.8 + service/status + 自我更新（2026-10-22）

对照源：`oss/docs/third-party-report-v4-analysis.md`（Wave 4 备忘录第 12–19 刀）。
提交：`616de5e`（已部署 VPS 8081，内核已拉起）。基线未动（仍 v0.1.341，用户明确暂不跟进 v0.1.344）。

## 一、入口旁路 2.8 核对与修复

| 原版行为 | 我们之前 | 处理 |
|---|---|---|
| normalizeCidr：裸地址补 /32、/128，前缀越界拒绝 | 标识原样进 nft set，`192.168.1.0/33` 会让整条脚本加载失败 | `arp.normalize_cidr()`，坏项丢弃 |
| normalizeMac：短横线转冒号，六组校验 | 正则只认冒号，短横线 MAC 会被当成 IP 标识 | `normalize_mac()` + `is_mac` 认短横线 |
| bypassPorts 黑白名单两个字段不合并 | 前端存 `port_list_mode` + `bypass_ports_white`，但 `settings_put` 白名单无此二键，**保存时静默丢弃**；后端恒读 black 模式 | db 白名单补二键；app 按模式选串（`port_list_mode` 优先，兼容旧 `bypass_ports_mode`） |
| parsePortSpec：一条坏项否决整串 | 端口串原样进 `{ports}`，坏项导致整条脚本失效 | `parse_port_spec()`，坏串整条端口规则不生成 |
| tunTcpMss：0 或 536–65495 | 无校验，域外值原样写 `maxseg` | 域外值直接关断 |
| MAC-only admit 路由一条规则都不产生 | 我们的 whitelist 模型下 MAC-only 会生成 macwhitelist 规则 | **差异待确认**：两者终端模型结构不同（原版 admit 块的门是 `admit.ips.length`）；我们的语义自洽，不照搬该怪癖 |
| 默认 profile 产出空字符串 | 不适用：原版写的是独立旁路文件，我们生成的是整张表；旁路相关段落本身已是条件渲染 | 不改 |

校验：本地断言脚本（CIDR/MAC/端口/MSS/坏项隔离）+ `test_selfupdate.py` 13 过 + `test_panel.py` 自测过。

## 二、service/status 语义核对

- **running 判定**：我们是 pid 存活判定，天然免疫原版 procd「同时印 running 和 no instances」的陷阱；修了一个真缺口：`_read_pid` 原先把 EPERM（其他用户的进程）误判为死亡，现 EPERM 算活着（与原版 pid 存活判定一致）。
- **uptimeSeconds null 语义**：已符合（没跑时为 None → null）；我们的 uptime 取 pidfile/proc 目录 mtime，绕开了原版 `/proc/pid/stat` 切分 comm 括号的坑。
- **冲突检测（conflicts/conflictAutoStopped）**：缺口。原版扫 OpenClash 等冲突代理（init 状态 + argv 扫描）；我们无此功能，Debian 下等价实现需另设计（避免把自家内核误判），本次未做，留待拍板。
- **deploy/state 永不 null**：原则已符合（无部署时返回对象而非 null），形状为自有 API，不强制对齐原版。

## 三、自我更新（按原版 update.sh 架构补齐我们的 git 机制）

我们已有 git 版自我更新（check/apply/log），但缺原版 2.1 的关键语义，本次补齐：

- **状态文件** `/tmp/openbox-oss-update.status`（key=value）：apply 起 detached applier 时写 `stage=running + pid`；applier 脚本加 EXIT trap，退出写 `done`/`failed`。
- **running 只认 pid 存活**：`read_status()` 杀掉的 applier 留下的 `stage=running` 不再锁死按钮；读取永不抛错。
- **apply 409 防重入**：进行中再次 apply 答 409（对标原版 run 的 409）。
- **cancel**：`POST /api/panel/update/cancel`，TERM→3s→KILL，写 `cancelled`。
- **notes**：`GET /api/panel/update/notes`，返回本地最近 20 条提交 + pending 更新信息（我们没有 GitHub releases，提交历史即更新内容）。
- **status 端点**：`GET /api/panel/update/status` 新增 `run` 字段；前端现有 check 调用不受影响。

VPS 验证：面板重启后 active；内核 running（pid 2648437）；update/status 的 run 为 idle、local_commit 为 616de5e；notes 返回 20 条，最新即本次提交；端口白名单键往返持久化验证后已恢复 black/空（用户此前未配端口旁路）。

## 四、未做（用户明确暂缓）

- 对照基线 v0.1.341 → v0.1.344 跟进。
- service/status 冲突代理检测。
- 自我更新前端 UI（后端接口已就绪，前端仍只有 check 入口）。
