# OpenBox-OSS

OpenWrt 一体化透明代理方案的**开源重构**（clean-room reimplementation）。

> 定位：与上游 Open-Box（闭源专有软件）行为兼容、代码完全独立重写的开源版本。
> 本分支不包含任何 Open-Box 闭源二进制与混淆产物，不做反编译 / 反汇编 / 逆向。
> 详细边界见 [BOUNDARY.md](BOUNDARY.md)。项目名称为暂定，正式发布前确认。

## 功能目标（对标公开文档描述的行为）

- 一条命令完成 sing-box 内核 + 管理面板的安装（OpenWrt / Debian / Docker）
- 浏览器面板完成订阅、节点、站点集分流、DNS、防火墙配置，无需手写配置文件
- 订阅解析：Clash YAML、base64 分享链接、常见 sing-box 分享链接
- 节点组：自动择优（urltest）、手动选择（select）、故障转移
- 目标分流：站点集（域名 / 后缀 / 关键词 / IP 段 / 规则集），先命中先生效
- DNS 分流：国内外上游分离、防污染
- TUN / nftables 透明代理，组件统一升级

## 当前进度

- [x] Phase 0：分支骨架、许可边界、首个模块 `core/`（订阅解析 → sing-box 配置生成）
- [ ] Phase 1：配置生成器完善（Clash YAML、规则集、DNS 策略）
- [ ] Phase 2：管理面板（后端 + 前端）
- [ ] Phase 3：安装 / 升级 / 卸载脚本开源重写
- [ ] Phase 4：客户端（长期可选）

路线图见 [docs/roadmap.md](docs/roadmap.md)。

## 快速试用（Phase 0 模块）

纯标准库，无第三方依赖：

```bash
cd oss
# 用示例订阅生成 sing-box 配置
python3 -m core.cli build --sub tests/sample-sub.txt --sites tests/sample-sites.json -o /tmp/config.json
python3 -m json.tool /tmp/config.json | head -50
# 跑自检
python3 -m tests.test_core
```

## 许可

- 本分支新增代码：MIT（见 [LICENSE](LICENSE)）
- 第三方组件：sing-box（GPL）、zashboard 基座（MIT）、Node.js、Geo 数据等，各按原许可；随包保留原始许可证
- 上游 Open-Box 自有程序：闭源专有许可，**不在本分支内**
