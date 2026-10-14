# 内核构建（sing-box 1.14.1-openbox-tcp23）

`.github/workflows/kernel.yml` 从上游 Release 发布的 **GPL 源码包**
构建魔改 sing-box 内核，产物为 linux amd64 / arm64 的静态二进制，
作为 workflow artifact 提供下载。

- 源码包：`https://github.com/liandu2024/Open-Box/releases/download/v0.1.326/sing-box-1.14.1-openbox-tcp23-source.tar.gz`
- 锁定哈希：`daf38f19ec94ccdb0c3046de57f06f4950356b2f1be2850586b4988d844150a5`
  （workflow 会校验，不一致直接失败）
- 构建脚本：源码包内的 `open-box-patch/build.sh`（上游自己的构建流程：
  固定顺序打补丁 → 跑补丁回归测试 → 按 `versions.sh` 的 tags/ldflags/Go 版本静态编译）
- Go 版本：`versions.sh` 里 `SINGBOX_GO_VERSION`（当前 1.25.5），workflow 自动读取

## 触发

- 手动：Actions 页 → "Kernel (sing-box tcp23)" → Run workflow
- 自动：`oss/kernel/**` 或 workflow 本身有改动并推送到 `oss` 分支时

## 使用产物

1. 从 Actions 运行页下载 `sing-box-tcp23-linux-amd64`（x86 试用机）
   或 `sing-box-tcp23-linux-arm64`（多数路由器）。
2. 放到面板能找到的位置并赋予执行权限：
   ```bash
   install -m 0755 sing-box /usr/local/bin/sing-box
   ```
   或用环境变量 `OPENBOX_SINGBOX_BIN=/path/to/sing-box` 指定。
3. 路由器一键安装：`oss/scripts/install.sh --kernel-url <产物直链>`。

## 许可

- 内核源码：GPL（随上游源码包），构建产物同样按 GPL 分发；
  产物 bundle 内已附带 `LICENSE`。
- 本分支面板/脚本代码：MIT。两者是独立作品，按各自许可使用。
- 构建过程不涉及任何反编译/逆向：输入是上游公开发布的源码包。
