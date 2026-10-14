# 魔改 sing-box 内核源码分析（1.14.1-openbox-tcp23）

来源：上游官方 Release v0.1.326 附件 `sing-box-1.14.1-openbox-tcp23-source.tar.gz`
（3.6MB，sha256 与官方公布一致，已校验）。GPL 许可，本分支可合法使用、修改、再分发。

## 结论先行

- 源码树是**已打好补丁**的完整 sing-box（`open-box-patch/*.patch` 均已应用进树，
  另有 `openbox_*` 新增文件与测试）。
- "tcp23" 是其补丁系列的第 23 代命名，内容是**传输层/路由管理层面的加固补丁集**，
  不是换内核。
- 构建可复现：`open-box-patch/manifest.py` 记录每次构建的输入哈希（补丁、新增文件、
  versions.sh），`compare` 可验证两个产物是否同一内核。
- 路由器内核与客户端库（Android `libbox.so` / iOS Libbox.xcframework / macOS 客户端）
  **由同一套补丁源码树构建**（`build-libbox.sh`，gomobile），仅入口与 target 不同；
  iOS 额外加 `with_low_memory` tag（网络扩展 50MB 上限）。

## 补丁清单（open-box-patch/）

| 补丁 | 说明 |
|---|---|
| `outbound-hot-replace.patch` (tcp13) | 出站管理器删除前先检查依赖，避免上游"先删后查"留下的半残状态；支撑**切换线路不重启内核** |
| `sagernet-nftables-reply-buffer.patch` (tcp17) | nftables 批量下发前按条数放大 netlink 接收缓冲（SO_RCVBUFFORCE），修复 `ENOBUFS` 导致 auto_redirect 起不来（iStoreOS 真实故障） |
| `low-memory.patch` (tcp20) | URL 测速改用有界 worker 池，替代 sing 的 batch.Go（每成员一 goroutine 驻留），一轮测速省约 5MB |
| `sing-socks-udp-relay.patch` | SOCKS UDP 中继地址修正（`openboxRelayAddress`） |
| `expected-status.patch` (tcp19) | URL 测速支持期望 HTTP 状态码（仿 mihomo expected-status），403/404 的节点不再被误判健康 |
| `openbox_pkg*.go` | 自有 Go 包：conntrack 集成（Linux）、direct-answer 等 |
| `openbox_*_test.go` | 对应测试：cached_packet、hot_outbound、udp_route、tcp 短连接、rule_set_watch、reality_mlkem |

## 本分支的使用方式

- 可直接用此源码树构建内核（需 Go 1.25.5+），或 cherry-pick 其中通用补丁
  （hot-replace、expected-status、low-memory 对任何 sing-box 下游都有价值）。
- 补丁注释为中英双语且写明了故障背景，读 `open-box-patch/` 即可理解每处改动的动机。
- 注意：不要把上游闭源的 `clients/core/obclient` 绑定逻辑误认为 GPL 义务之外的东西——
  它在源码包内，随包以 GPL 分发，可直接用。

## 未验证

- 完整构建（本机无 Go 1.25 工具链；CI 中补）。
- 与上游 sing-box v1.14.1 的逐行 diff（补丁文件本身即 diff，可按需展开）。
