# Third-Party Notices — geodata

The `geodata/` directory (local sing-box rule-set `.srs` files, downloaded on
demand from the public upstream CDNs, never copied from any other product)
contains data from the following sources:

## geosite-*.srs — SagerNet/sing-geosite

- Source: https://github.com/SagerNet/sing-geosite (rule-set branch)
- Generator: GPL-3.0-or-later, copyright (C) 2022 nekohasekai
- Rule data: v2fly/domain-list-community, MIT License:

  MIT License

  Copyright (c) 2018-2019 V2Ray

  Permission is hereby granted, free of charge, to any person obtaining a copy
  of this software and associated documentation files (the "Software"), to deal
  in the Software without restriction, including without limitation the rights
  to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
  copies of the Software, and to permit persons to whom the Software is
  furnished to do so, subject to the following conditions:

  The above copyright notice and this permission notice shall be included in all
  copies or substantial portions of the Software.

## geoip-*.srs — SagerNet/sing-geoip

- Source: https://github.com/SagerNet/sing-geoip (rule-set branch)
- Generator: GPL-3.0-or-later, copyright (C) 2022 nekohasekai
- IP data: MaxMind GeoLite2 — "This product includes GeoLite2 data created by
  MaxMind, available from https://www.maxmind.com".

---

# Third-Party Notices — zashboard (oss-zashboard branch only)

The `oss/dashboard/zashboard-src/` tree is based on zashboard v3.22.0, modified
for Open-Box ("二开"). The upstream `LICENSE` (MIT) file is kept verbatim in
`oss/dashboard/zashboard-src/LICENSE`.

- Source: https://github.com/Zephyruso/zashboard (tag v3.22.0 — the last
  upstream release with sing-box support; upstream removed sing-box support in
  v3.23.0, see upstream `docs/sing-box-deprecation.md`)
- License: MIT License, copyright (c) Zephyruso (see LICENSE file for the
  full text and exact copyright line)
- Modifications by Open-Box OSS branch (not upstream):
  - `src/openbox/` — panel API wrapper, login gate reusing the Flask panel
    session, auto-provisioning of the local sing-box Clash API backend
  - `src/views/manage/` — new "Manage" section; subscription management ported
    from the previous self-developed UI, further modules planned
  - `src/router/index.ts`, `src/constant/index.ts`, `src/main.ts`,
    `src/i18n/*`, `index.html` — route/nav/i18n/branding integration
  - backend: `experimental.clash_api` listen address/secret made configurable
    (`clash_api_listen`, `clash_api_secret`), `GET /api/openbox/clash-config`
