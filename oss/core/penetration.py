"""规则穿透测试：输入域名/IP，返回匹配的规则、出口链路。

对标原版 POST /api/openbox/penetration 的公开行为。

规则集引用（前置 geosite/geoip、站点集 rule_sets）经 sing-box
rule-set decompile 展开后匹配（geodata.expand_geosite_split /
expand_geoip，与入口旁路同款解码、失败闭合返 []，缺文件时与
内核丢弃该规则的行为一致）。展开器可注入，便于无 sing-box 测试。
"""

import ipaddress
import socket

from core import geodata as _gd


def _is_ip(s: str) -> bool:
    try:
        ipaddress.ip_address(s)
        return True
    except ValueError:
        return False


def _match_domain(rule_type: str, rule_value: str, domain: str) -> bool:
    """检查域名是否匹配规则。

    语义对标 sing-box（路由金标准 81 例验证）：
    - domain 精确匹配：大小写敏感（大写规则值不命中），仅去尾点；
    - domain_suffix / domain_keyword：大小写不敏感。
    """
    domain = domain.rstrip('.')
    if rule_type == 'domain':
        return domain == rule_value.strip()
    domain = domain.lower()
    val = rule_value.lower().strip()
    if rule_type == 'domain_suffix':
        return domain == val or domain.endswith('.' + val.lstrip('.'))
    elif rule_type == 'domain_keyword':
        return val in domain
    return False


def _match_ip(rule_value: str, ip_str: str) -> bool:
    """检查 IP 是否匹配 CIDR。"""
    try:
        return ipaddress.ip_address(ip_str) in ipaddress.ip_network(rule_value, strict=False)
    except ValueError:
        return False


def _match_expanded_geosite(query: str, name: str, geosite_split) -> str | None:
    """Match a domain against an expanded geosite set.

    Returns the matched entry ('domain: x' / 'domain_suffix: x') or None.
    Exact and suffix entries are kept apart: treating an exact domain as
    a suffix would over-match subdomains.
    """
    domains, suffixes = geosite_split(name)
    for d in domains:
        if _match_domain("domain", d, query):
            return f"domain: {d}"
    for s in suffixes:
        if _match_domain("domain_suffix", s, query):
            return f"domain_suffix: {s}"
    return None


def penetrate(cfg, query: str,
              geosite_split=None, geoip_expand=None) -> dict:
    """穿透测试主函数。

    Args:
        cfg: AppConfig 对象
        query: 域名或 IP
        geosite_split: geosite 展开函数 (name) -> (domains, suffixes)，
            默认 geodata.expand_geosite_split；测试可注入桩。
        geoip_expand: geoip 展开函数 (name) -> [cidr]，
            默认 geodata.expand_geoip；测试可注入桩。

    Returns:
        {
            "query": str,
            "is_ip": bool,
            "resolved_ips": [str],  # 域名解析结果
            "matched": {
                "source": "front" | "siteset" | "fallback",
                "rule_type": str,
                "rule_value": str,
                "rule_note": str,
                "target": str,  # 出口
            } | None,
            "dns_server": str,  # 将使用的 DNS
        }
    """
    query = query.strip()
    is_ip = _is_ip(query)
    if geosite_split is None:
        geosite_split = _gd.expand_geosite_split
    if geoip_expand is None:
        geoip_expand = _gd.expand_geoip
    result = {
        "query": query,
        "is_ip": is_ip,
        "resolved_ips": [],
        "matched": None,
        "dns_server": "dns-direct",
    }

    # 域名解析（仅用于展示）
    if not is_ip:
        try:
            _, _, ips = socket.gethostbyname_ex(query)
            result["resolved_ips"] = ips[:5]
        except Exception:
            pass

    # 1. 前置规则（按顺序）
    for fr in (cfg.front_rules or []):
        if not isinstance(fr, dict):
            continue
        if not fr.get("enabled", True):
            continue
        rtype = fr.get("rtype", "domain_suffix")
        val = fr.get("domain", "")
        target = fr.get("target", "auto")
        note = fr.get("note", "")

        matched = False
        if is_ip:
            # IP 匹配 ip_cidr 与 geoip（展开后按 CIDR 判定）
            if rtype == "ip_cidr" and _match_ip(val, query):
                matched = True
            elif rtype == "geoip":
                # 命名与生成侧一致：geoip-{val}
                for cidr in geoip_expand(f"geoip-{val}"):
                    if _match_ip(cidr, query):
                        matched = True
                        break
        else:
            # 域名匹配域名类规则与 geosite（展开后按 exact/suffix 判定）
            if rtype in ("domain", "domain_suffix", "domain_keyword"):
                if _match_domain(rtype, val, query):
                    matched = True
            elif rtype == "geosite":
                # 命名与生成侧一致：geosite-{val}；展开失败返 [] 即不命中，
                # 与内核缺文件丢弃该规则的行为一致
                if _match_expanded_geosite(query, f"geosite-{val}", geosite_split):
                    matched = True

        if matched:
            result["matched"] = {
                "source": "front",
                "source_name": "前置自定义分流",
                "rule_type": rtype,
                "rule_value": val,
                "rule_note": note,
                "target": target,
            }
            result["dns_server"] = "dns-direct" if target in ("direct", "reject") else "dns-proxy"
            return result

    # 2. 站点集（按顺序）
    for ss in (cfg.site_sets or []):
        if not getattr(ss, 'enabled', True):
            continue
        action = getattr(ss, 'action', 'proxy')
        name = getattr(ss, 'name', '')

        matched = False
        matched_detail = ""

        if is_ip:
            # IP 匹配 ip_cidr 与 geoip 规则集
            for cidr in (getattr(ss, 'ip_cidr', []) or []):
                if _match_ip(cidr, query):
                    matched = True
                    matched_detail = f"ip_cidr: {cidr}"
                    break
            if not matched:
                for rs in (getattr(ss, 'rule_sets', []) or []):
                    if not rs.startswith("geoip-"):
                        continue
                    for cidr in geoip_expand(rs):
                        if _match_ip(cidr, query):
                            matched = True
                            matched_detail = f"rule_set {rs}: ip_cidr: {cidr}"
                            break
                    if matched:
                        break
        else:
            # 域名匹配：字面规则优先，规则集引用随后（同一站点集内结果相同，
            # 只影响 matched_detail 的展示）
            for d in (getattr(ss, 'domains', []) or []):
                if _match_domain('domain', d, query):
                    matched = True
                    matched_detail = f"domain: {d}"
                    break
            if not matched:
                for ds in (getattr(ss, 'domain_suffix', []) or []):
                    if _match_domain('domain_suffix', ds, query):
                        matched = True
                        matched_detail = f"domain_suffix: {ds}"
                        break
            if not matched:
                for kw in (getattr(ss, 'domain_keyword', []) or []):
                    if _match_domain('domain_keyword', kw, query):
                        matched = True
                        matched_detail = f"domain_keyword: {kw}"
                        break
            if not matched:
                for rs in (getattr(ss, 'rule_sets', []) or []):
                    if not rs.startswith("geosite-"):
                        continue
                    hit = _match_expanded_geosite(query, rs, geosite_split)
                    if hit:
                        matched = True
                        matched_detail = f"rule_set {rs}: {hit}"
                        break

        if matched:
            # 站点集的出口是 group
            target = getattr(ss, 'group', '所有-自动')
            result["matched"] = {
                "source": "siteset",
                "source_name": f"站点集: {name}",
                "rule_type": "siteset",
                "rule_value": matched_detail,
                "rule_note": "",
                "target": target,
            }
            result["dns_server"] = "dns-direct" if action == "direct" else "dns-proxy"
            return result

    # 3. 兜底
    fallback = getattr(cfg, 'final_outbound', '所有-自动')
    result["matched"] = {
        "source": "fallback",
        "source_name": "兜底",
        "rule_type": "fallback",
        "rule_value": "",
        "rule_note": "",
        "target": fallback,
    }
    return result
