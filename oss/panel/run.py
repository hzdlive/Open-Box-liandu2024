"""Dev entry point: python3 panel/run.py"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from panel.app import create_app  # noqa: E402

if __name__ == "__main__":
    db_path = os.environ.get("OBX_DB", os.path.expanduser("~/.openbox-oss/panel.db"))
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    app = create_app(db_path)
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "8080")))
