# REA 报告有用情报摘录（v0.1.330 逆向分析报告）

> 来源：用户上传 `open-box-rea-report.zh.html`（REA v6.5.0 对 v0.1.330 静态分析）
> 注意：仅提取公开行为层面的事实（API 路径、参数、枚举值、行为规则），不复制任何实现代码。

## 一、缺失的 API 端点（前端实际调用，我们尚未实现）

| 端点 | 用途 | 优先级 |
|------|------|--------|
| POST /api/openbox/penetration | 规则穿透查询：输入域名/IP，返回匹配规则、规则集、出口链路 | 高 |
| POST /api/openbox/terminal-test + GET /capability | 终端连通性按需探测（先探测能力，不静默降级） | 高 |
| POST /api/openbox/dns/flush-cache | 清除 dnsmasq 缓存 + 内核缓存 | 中 |
| GET/POST /api/openbox/dns/region-detect | 地区自动检测（按出口公网 IP） | 中 |
| /api/openbox/subscription-shares (5个) | 订阅分享：CRUD + regenerate（令牌寻址 /sub/:token，可单独启用/禁用/复制/刷新/删除，重新生成使旧令牌失效） | 高 |
| GET /api/openbox/failover/status + POST /recheck | 故障转移状态查询与手动重检 | 高 |
| GET /api/openbox/site-latency + /history | 站点延迟历史 | 低 |

## 二、必须遵守的不变量（26.3）

1. **站点集自上而下，先匹配者胜** ✅ 已有
2. **IP/域名隔离**：域名匹配的连接绝不落入 IP/geoip 规则；IP 发起的连接绝不匹配域名规则 ✅ 已有
3. **链式代理绝不能进入动态分组** ⚠️ 需验证前端是否阻止
4. **切换站点集直连↔代理不重启内核**：只重写"切换规则集"，已建立连接存活，新连接/DNS 1秒内跟进 ⚠️ 需验证我们是否误重启
5. **大陆代理 DNS 不得用上游 DNS**：默认 TCP 1.1.1.1；大陆之外默认就是上游 DNS；港澳台算大陆之外 ✅ 已有默认值，需加拒绝逻辑（验收 #16）
6. **导出绝不含面板密码** ✅ 已有
7. **故障转移**：仅主宕机才切备用，恢复时切回；恢复保持 60s；失败阈值=2次**连续**失败；all-failed 时切到 reject 出站并每分钟重试

## 三、枚举对齐（26.5）

- 出站类型 `id`：direct, reject, rejectdrop, compatible, pass, dns, selector, fallback, urltest, **smart, loadbalance**
  - ⚠️ 我们缺 `smart` 和 `loadbalance` 两种组类型
- 导出分组 `od`：panel, subscriptions, groups, routing, clients, chain, dns, kernel, share, apps

## 四、故障转移参数（26.4，硬性）

- 最多 3 通道：primary, backup-1, backup-2
- 探测间隔 300s，通道容差 100ms，探测超时 5000ms
- 失败阈值 2（连续），恢复保持 60s，恢复保持 UI 钳制 0…86400s
- 11 种失败原因码不可合并：closed, dns, error, invalid, notFound, refused, status, timeout, tls, unreachable, unstable
- 原因码另有：initial（初始选择）, lane-failed, restore（主恢复）, priority, recovered, all-failed

## 五、验收标准（26.6，测试清单）

- #13 切换站点集不重启，已建立连接不断
- #14 QUIC 拦截默认开启，不影响直连 ✅
- #15 地区自动检测在全新安装/升级/恢复默认值时运行
- #16 大陆代理 DNS 选上游 DNS 要被拒绝并给出解释 ⚠️ 待实现
- #17 缓存命中的查询仍出现在 DNS 日志中
- #21 禁用分享停止 /sub/:token；重新生成使旧链接失效
- #23 导出不含密码；导入按分组选择性恢复 ✅

## 六、其他关键行为

- **DNS 接管三种模式**：dnsmasq 转发 / 防火墙劫持 / 禁用 ✅ 已有
- **入口绕过**：开关默认开启；两种自动模式 default-release（FakeIP开+兜底直连）与 default-enter；模式变更只重写规则集文件
- **链式代理位置**：位于前置节点/分组之后的出口（socks5/http/https）；编辑对话框可测速并报告出口 IP 与国家
- **订阅分享**：Clash YAML、base64、sing-box 链接；令牌寻址
- **更新**：先校验版本与完整性，已是最新则不下载 ✅
- **内核自报**：Clash API 自报为 mihomo/1.19.0（兼容第三方客户端），向 OB 基础设施标识为 Open-Box/1.0
- **i18n**：1,828 个键、3 种语言；Open-Box 新增约 88%
- **面板包**：573KB ESM，未混淆（但闭源，不可复制）
- **许可证**：激活无客户端校验，纯服务端 Ed25519（不在复刻范围）
