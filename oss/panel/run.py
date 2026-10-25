"""Dev entry point: python3 panel/run.py"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from panel.app import create_app  # noqa: E402

if __name__ == "__main__":
    db_path = os.environ.get("OBX_DB", os.path.expanduser("~/.openbox-oss/panel.db"))
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    app = create_app(db_path)
    # Kernel autostart (only for file DBs): the panel owns the kernel, so
    # this flag — not an init script — is what "boot the kernel" means.
    if db_path != ":memory:":
        from panel.app import maybe_autostart_kernel
        maybe_autostart_kernel(db_path)
    # Traffic accounting collector (only for file DBs; needs the kernel up).
    # Disabled by default; enable with OBX_TRAFFIC_COLLECT=1.
    if db_path != ":memory:" and os.environ.get("OBX_TRAFFIC_COLLECT") == "1":
        import threading
        from core import traffic as _traffic
        _stop = threading.Event()
        _t = threading.Thread(target=_traffic.watch_loop,
                              args=(db_path,), kwargs={"stop": _stop}, daemon=True)
        _t.start()
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "8080")),
            threaded=True)  # 避免单线程僵死：慢请求（订阅刷新/节点测速）不阻塞全站
