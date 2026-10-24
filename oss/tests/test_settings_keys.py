"""Regression: every key the settings UIs send via PUT /api/settings must
actually persist. PUT silently drops keys outside DEFAULT_SETTINGS, so a
renamed frontend key looks saved but never sticks (this caught 7 dashboard
keys whose names diverged from the backend canonical names).

KNOWN_DEAD are controls that send a key no backend code reads: they are
placebos, kept visible deliberately until someone decides to wire or remove
them -- the test pins them so a new dropped key cannot hide among them.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "oss"))

from panel import db as dbmod  # noqa: E402

ALLOWED = set(dbmod.DEFAULT_SETTINGS)
KNOWN_DEAD = {
    # dashboard toggle; backend enable_ipv6 comes from the nft endpoint
    # query param (?ipv6=), never from settings.
    "ipv6",
    # dashboard input; no backend reader anywhere.
    "test_expected",
    # legacy toggle; no backend reader anywhere.
    "tun_only",
}


def dashboard_keys():
    src = (ROOT / "oss/dashboard/zashboard-src/src/views/manage/SettingsTab.vue"
           ).read_text(encoding="utf-8")
    keys = set(re.findall(r"save(?:Key|Bool)\('([^']+)'", src))
    m = re.search(r"const s = ref<any>\(\{(.*?)\}\)", src, re.S)
    assert m, "s initial object not found in SettingsTab.vue"
    keys |= set(re.findall(r"(\w+):", m.group(1)))
    return keys


def legacy_keys():
    src = (ROOT / "oss/panel/frontend/src/views/Settings.vue"
           ).read_text(encoding="utf-8")
    keys = set()
    for block in re.findall(r"put\('/api/settings', \{(.*?)\}\)", src, re.S):
        keys |= set(re.findall(r"(\w+):", block))
    assert keys, "no PUT /api/settings bodies found in legacy Settings.vue"
    return keys


def main():
    for origin, keys in (("dashboard", dashboard_keys()),
                         ("legacy", legacy_keys())):
        bad = sorted(k for k in keys if k not in ALLOWED and k not in KNOWN_DEAD)
        assert not bad, f"{origin} sends settings keys that PUT drops: {bad}"
        print(f"OK: {origin} settings keys all persist "
              f"({len(keys)} keys, {len(keys & KNOWN_DEAD)} known-dead)")
    print("OK: settings keys regression")


if __name__ == "__main__":
    main()
