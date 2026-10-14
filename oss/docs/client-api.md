# 客户端 API 规范（Phase 4 前置）

> 状态：设计稿（2026-10-14）。选型无关——Tauri / Flutter / 原生都按此契约实现。
> 覆盖源项目客户端的公开行为：路由器配对、订阅同步、模式切换、
> Wi-Fi 自动暂停、分享链接导入。不涉及闭源实现细节。

## 1. 配对（pairing）

面板「配对」页生成一次性二维码，内容示例：

```
openbox://pair?host=192.168.1.1&port=8080&token=PAIR_ONCE_TOKEN
```

流程：

1. 面板 `POST /api/pair/code` 生成一次性 token（10 分钟有效，一次有效）。
2. 客户端扫码 → `POST /api/pair/confirm {"token": "PAIR_ONCE_TOKEN", "device": "Pixel 8"}`。
3. 面板返回长期 `client_token`（可吊销，面板可列出/删除已配对设备）。
4. 客户端之后所有 `/api/client/*` 请求带 `Authorization: Bearer <client_token>`。

`GET /api/pair/devices` / `DELETE /api/pair/devices/{id}`：管理已配对设备。

## 2. 鉴权模型

面板当前无登录鉴权（本地开发暂行，见 roadmap）。路由器部署前必须补：

- 人用面板：密码登录 → session cookie（Flask）。
- 客户端 App：配对 token → Bearer（无密码，避免在 App 里存面板密码）。
- 配对接口本身限流（防局域网爆破一次性 token）。

## 3. 客户端接口

基路径 `/api/client`，全部需要 Bearer。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/client/status` | 内核运行状态、当前出口、流量（up/down）、运行时长 |
| GET | `/api/client/nodes` | 节点列表：`[{tag, protocol, server, latency_ms, ok}]`（latency 来自面板健康检查） |
| GET | `/api/client/groups` | 节点组列表及当前选中 |
| POST | `/api/client/groups/{name}/select` | 切换 selector 组当前出口 `{"tag": "..."}`（经 clash API） |
| GET | `/api/client/config` | 下发客户端本地 sing-box 配置（见 §4） |
| POST | `/api/client/mode` | 切换模式 `{"mode": "global" \| "rule" \| "direct"}` |
| GET | `/api/client/mode` | 查询当前模式 |
| POST | `/api/client/subscriptions/sync` | 订阅同步（见 §5） |
| GET | `/api/client/wifi-policy` | Wi-Fi 自动暂停策略（见 §6） |
| PUT | `/api/client/wifi-policy` | 更新策略（SSID 白名单等） |

`status` 示例：

```json
{
  "running": true,
  "current_outbound": "vmess-demo",
  "mode": "rule",
  "traffic": {"up": 123456, "down": 7890123},
  "uptime_s": 3600
}
```

## 4. 客户端本地配置下发

`GET /api/client/config` 返回可直接喂给客户端 sing-box 内核的配置：

- 入站：客户端本地 `tun` + `mixed`（127.0.0.1:7890）。
- 出站：与面板相同的节点，但 `final` 指向客户端当前模式对应的出口；
  `mode=global` 时 final 指向所选节点组，`direct` 时指向 direct。
- 路由规则：复用面板站点集（客户端可选择"跟随路由器"或"仅本地规则"，
  见 `?ruleset=follow|local` 参数）。

客户端内核可用 stock sing-box 或 GPL tcp23 构建（gomobile 产物对应
客户端的 libbox.so 角色）。

## 5. 订阅同步协议

`POST /api/client/subscriptions/sync`，双向：

请求：

```json
{
  "direction": "pull",
  "client_rev": 12
}
```

- `pull`：客户端拉取路由器订阅变更。响应 `{"rev": 15, "nodes": [...], "deleted": [...]}`，
  `rev` 为面板侧单调版本号；`client_rev` 为客户端上次同步到的版本。
- `push`：客户端把自己导入的订阅推给路由器（扫码/粘贴链接的场景），
  请求体为 `{"direction": "push", "content": "<订阅文本>", "format": "auto"}`，
  面板解析入库后返回新增节点数。复用现有 `/api/subscriptions` 解析能力。

冲突策略：以路由器为权威，客户端本地新增在 push 后以上行为准。

## 6. Wi-Fi 自动暂停

纯客户端本地行为（对应 APK 的 Wi-Fi/定位权限与"指定 Wi-Fi 自动暂停"）：

- 客户端监听系统 Wi-Fi 状态，当前 SSID 命中豁免名单 → 自动暂停本地代理
  （或切换为 direct 模式），离开名单 → 恢复。
- 豁免名单由面板统一下发：`GET /api/client/wifi-policy` →

```json
{"enabled": true, "pause_ssids": ["Home-5G", "Office"], "action": "pause"}
```

`action` 为 `pause`（停内核）或 `direct`（切直连模式）。

## 7. 分享链接导入

客户端注册 `openbox://`、`ss://`、`vless://` 等 scheme（对标 APK manifest）：

- 收到分享链接 → 优先走 `POST /api/client/subscriptions/sync`（push）同步到路由器；
- 无配对时 → 存为客户端本地订阅（Phase 4 客户端本地存储自行实现）。

面板侧已有 `/api/share`（节点→链接）与之对应，形成闭环。

## 8. 安全说明

- 默认局域网 HTTP + token；面板应允许改端口，client_token 支持吊销。
- 一次性配对 token 10 分钟过期，一次有效。
- 不在日志中打印 token；面板日志脱敏。

## 9. 与选型的关系

本规范定死之后，Phase 4 任选其一开工均可：

- **Tauri**：Rust 侧跑 sing-box（ffi/子进程），前端复用现有面板页面思想；
- **Flutter**：dart 侧调 sing-box-mobile（对应 libbox.so 的 gomobile 路线）；
- **原生**（Kotlin/Swift）：各平台调对应 sing-box 绑定。

选型只影响"客户端怎么跑内核"，不影响"客户端怎么跟路由器说话"。
