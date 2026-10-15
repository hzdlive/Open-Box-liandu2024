#!/bin/sh
# openbox-oss 一键诊断（只读：只收集信息，不修改任何东西）
# 在面板所在机器上以 root 运行：
#     sh diagnose.sh
# 把输出全文发给助手，即可定位"哪哪都不上"的问题。
# 注：本脚本不输出订阅链接、密码等敏感信息，可放心粘贴。
set -u

PORT="${PORT:-8080}"
DB="${OBX_DB:-$HOME/.openbox-oss/panel.db}"
WD="${OPENBOX_WORKDIR:-$HOME/.openbox-oss}"
SB="${SING_BOX_BIN:-/usr/local/bin/sing-box}"

sec() { echo; echo "===== $1 ====="; }
have() { command -v "$1" >/dev/null 2>&1; }

sec "0. 时间"
date

sec "1. 系统"
uname -a
(have lsb_release && lsb_release -ds) 2>/dev/null || head -1 /etc/os-release 2>/dev/null || head -1 /etc/openwrt_release 2>/dev/null
uptime 2>/dev/null
df -h / | tail -1
free -m 2>/dev/null | head -2

sec "2. 代码版本（是否已 git pull 到最新）"
for d in "$HOME/workspace/openbox-oss" "$HOME/openbox-oss" /root/openbox-oss /opt/openbox-oss; do
  if [ -d "$d/.git" ]; then
    echo "checkout: $d"
    git -C "$d" rev-parse --short HEAD 2>/dev/null | sed 's/^/  commit: /'
    git -C "$d" rev-parse --abbrev-ref HEAD 2>/dev/null | sed 's/^/  branch: /'
    git -C "$d" log -1 --format='%ci %s' 2>/dev/null | sed 's/^/  date:   /'
    git -C "$d" status -sb 2>/dev/null | head -3 | sed 's/^/  /'
  fi
done

sec "3. 面板进程与端口"
ps aux 2>/dev/null | grep -E "run\.py|panel/app|gunicorn" | grep -v grep | head -5 || ps | grep -E "run\.py|panel" | grep -v grep | head -5
if have ss; then ss -ltnp 2>/dev/null | grep ":$PORT" || echo "端口 $PORT 未监听"
elif have netstat; then netstat -ltnp 2>/dev/null | grep ":$PORT" || echo "端口 $PORT 未监听"
else echo "(无 ss/netstat，跳过端口检查)"; fi
echo "--- http://127.0.0.1:$PORT/api/auth/status ---"
if have curl; then curl -s -m 8 "http://127.0.0.1:$PORT/api/auth/status"; echo
else echo "(无 curl，跳过)"; fi
echo "--- http://127.0.0.1:$PORT/ (前端首页状态码) ---"
if have curl; then curl -s -m 8 -o /dev/null -w "%{http_code}\n" "http://127.0.0.1:$PORT/"; fi

sec "4. 数据库"
ls -la "$DB" 2>/dev/null || echo "数据库文件不存在: $DB"
if have sqlite3 && [ -f "$DB" ]; then
  echo "--- 表 ---"; sqlite3 "$DB" ".tables" 2>/dev/null
  for t in subscriptions nodes groups; do
    printf "%s: " "$t"; sqlite3 "$DB" "SELECT COUNT(*) FROM $t;" 2>/dev/null || echo "?"
  done
  echo "--- 出站组名（检查 auto/manual 是否已迁移为 所有-自动/所有-手动）---"
  sqlite3 "$DB" "SELECT name FROM groups;" 2>/dev/null
  echo "--- 启用的订阅数 ---"
  sqlite3 "$DB" "SELECT COUNT(*) FROM subscriptions WHERE enabled=1;" 2>/dev/null || echo "?"
else echo "(无 sqlite3 或数据库不存在，跳过)"; fi

sec "5. 内核 sing-box"
[ -x "$SB" ] || SB="$(command -v sing-box 2>/dev/null || echo /usr/local/bin/sing-box)"
echo "binary: $SB"
if [ -x "$SB" ]; then "$SB" version 2>&1 | head -2; else echo "sing-box 不可执行"; fi
echo "--- pidfile: $WD/sing-box.pid ---"
if [ -f "$WD/sing-box.pid" ]; then
  PID="$(cat "$WD/sing-box.pid")"; echo "pid=$PID"
  ps -p "$PID" -o pid,etime,comm 2>/dev/null || echo "该 pid 无对应进程（僵尸 pidfile）"
else echo "无 pidfile"; fi
echo "--- 系统中所有 sing-box 进程 ---"
ps aux 2>/dev/null | grep "[s]ing-box" | head -5
echo "--- 配置校验: sing-box check -c $WD/config.json ---"
if [ -f "$WD/config.json" ]; then
  "$SB" check -c "$WD/config.json" 2>&1 | head -10
else echo "config.json 不存在: $WD/config.json"; fi
echo "--- 内核日志尾 30 行: $WD/sing-box.log ---"
tail -30 "$WD/sing-box.log" 2>/dev/null || echo "(无日志文件)"

sec "6. 面板日志"
if [ -n "${OBX_PANEL_LOG:-}" ]; then
  echo "OBX_PANEL_LOG=$OBX_PANEL_LOG"; tail -40 "$OBX_PANEL_LOG" 2>/dev/null || echo "(读不到)"
else echo "面板文件日志未启用（OBX_PANEL_LOG 未设置）"; fi
[ -f /tmp/openbox-oss-upgrade.log ] && { echo "--- /tmp/openbox-oss-upgrade.log 尾 20 行 ---"; tail -20 /tmp/openbox-oss-upgrade.log; }

sec "7. 网络连通（节点侧，非必需）"
if have curl; then curl -s -m 8 -o /dev/null -w "直连 baidu: %{http_code} (%{time_total}s)\n" "https://www.baidu.com" || echo "直连失败"; fi

echo; echo "===== 诊断结束 ====="
