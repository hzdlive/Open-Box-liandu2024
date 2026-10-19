"""Content filter ruleset parsers (Surge / QuantumultX).

Clean-room implementation of publicly observable behavior:
- Parse Surge and QuantumultX rule files into structured rules
- 512 KiB input limit
- Track skipped_* counters for unrepresentable content
- Extract domains for sing-box block rules (reject action only)

Based on third-party behavioral reports (not reversed code).
"""

from __future__ import annotations

import re

MAX_TEXT_BYTES = 512 * 1024  # 512 KiB limit (1:1 with original)


def parse_ruleset(text: str, dialect: str) -> dict:
    """Parse a Surge or QuantumultX ruleset.
    
    Args:
        text: raw rule text (max 512 KiB)
        dialect: "surge" or "quantumultx"
    
    Returns:
        {
            "rules": [{action, pattern, type, ...}],
            "hostnames": [...],
            "arguments": {"values": {}, "declared": []},
            "scripts": [{url, ...}],  # script URLs found (not downloaded)
            "skipped_scripts": int,
            "skipped_unsupported": int,
            "skipped_routing": int,
            "skipped_unrepresentable": int,
        }
    
    Raises:
        ValueError: if text exceeds 512 KiB
    """
    if len(text.encode('utf-8')) > MAX_TEXT_BYTES:
        raise ValueError(f"规则文本超过 512 KiB 上限")
    
    if dialect == "surge":
        return _parse_surge(text)
    elif dialect == "quantumultx":
        return _parse_quantumultx(text)
    else:
        raise ValueError(f"不支持的方言: {dialect}")


def _parse_surge(text: str) -> dict:
    """Parse Surge config sections: [Rule], [URL Rewrite], [Script], [MITM]."""
    result = {
        "rules": [],
        "hostnames": [],
        "arguments": {"values": {}, "declared": []},
        "scripts": [],
        "skipped_scripts": 0,
        "skipped_unsupported": 0,
        "skipped_routing": 0,
        "skipped_unrepresentable": 0,
    }
    
    current_section = None
    for line in text.split('\n'):
        line = line.strip()
        if not line or line.startswith('#') or line.startswith(';'):
            continue
        
        # Section header
        m = re.match(r'^\[(.+)\]$', line)
        if m:
            current_section = m.group(1).lower()
            continue
        
        if current_section == "rule":
            # Format: TYPE, PATTERN, POLICY [, ...]
            # e.g. "DOMAIN-SUFFIX, ads.example.com, REJECT"
            parts = [p.strip() for p in line.split(',')]
            if len(parts) < 3:
                result["skipped_unsupported"] += 1
                continue
            rtype, pattern, policy = parts[0].upper(), parts[1], parts[2].upper()
            
            if policy in ("REJECT", "REJECT-TINYGIF", "REJECT-DROP"):
                action = "reject"
            elif policy in ("DIRECT",):
                result["skipped_routing"] += 1
                continue
            else:
                # PROXY etc. - routing rules, not content filter
                result["skipped_routing"] += 1
                continue
            
            # Map Surge types to our model
            if rtype in ("DOMAIN", "DOMAIN-SUFFIX", "DOMAIN-KEYWORD"):
                result["rules"].append({
                    "action": action,
                    "pattern": pattern,
                    "type": "domain_suffix" if rtype == "DOMAIN-SUFFIX" else "domain",
                })
            elif rtype == "URL-REGEX":
                # URL regex: try to extract domain, else mark unrepresentable
                domain = _extract_domain_from_regex(pattern)
                if domain:
                    result["rules"].append({
                        "action": action,
                        "pattern": domain,
                        "type": "domain_suffix",
                        "source": "url_regex",
                    })
                else:
                    result["skipped_unrepresentable"] += 1
            else:
                result["skipped_unsupported"] += 1
        
        elif current_section == "url rewrite":
            # Format: PATTERN REPLACEMENT 301/302 or PATTERN - reject
            # e.g. "^https?://.*\\.ads\\.com/ - reject"
            parts = line.split()
            if len(parts) >= 2 and parts[-1].lower() == "reject":
                pattern = parts[0]
                domain = _extract_domain_from_regex(pattern)
                if domain:
                    result["rules"].append({
                        "action": "reject",
                        "pattern": domain,
                        "type": "domain_suffix",
                        "source": "url_rewrite",
                    })
                else:
                    result["skipped_unrepresentable"] += 1
            else:
                result["skipped_unsupported"] += 1
        
        elif current_section == "script":
            # Script references: only count, don't execute on router
            # Format: name = type=..., pattern=..., script-path=..., ...
            if "script-path" in line.lower() or "script_url" in line.lower():
                result["skipped_scripts"] += 1
                # Extract URL if present
                m = re.search(r'https?://[^\s,]+', line)
                if m:
                    result["scripts"].append({"url": m.group(0)})
            else:
                result["skipped_unsupported"] += 1
        
        elif current_section == "mitm":
            # MITM hostnames: hostname = %APPEND% example.com
            if "hostname" in line.lower():
                # Extract hostnames after =
                parts = line.split('=', 1)
                if len(parts) == 2:
                    hosts = [h.strip() for h in parts[1].split(',')]
                    hosts = [h for h in hosts if h and not h.startswith('%')]
                    result["hostnames"].extend(hosts)
    
    return result


def _parse_quantumultx(text: str) -> dict:
    """Parse QuantumultX sections: [rewrite_local], [filter_local], [mitm]."""
    result = {
        "rules": [],
        "hostnames": [],
        "arguments": {"values": {}, "declared": []},
        "scripts": [],
        "skipped_scripts": 0,
        "skipped_unsupported": 0,
        "skipped_routing": 0,
        "skipped_unrepresentable": 0,
    }
    
    current_section = None
    for line in text.split('\n'):
        line = line.strip()
        if not line or line.startswith('#') or line.startswith(';'):
            continue
        
        m = re.match(r'^\[(.+)\]$', line)
        if m:
            current_section = m.group(1).lower()
            continue
        
        if current_section == "rewrite_local":
            # Format: PATTERN url reject[-200] / reject-dict / reject-array
            # e.g. "^https?://.*\\.ads\\.com/ url reject"
            parts = line.split()
            if len(parts) >= 3 and parts[1].lower() == "url":
                action_part = parts[2].lower()
                if action_part.startswith("reject"):
                    pattern = parts[0]
                    domain = _extract_domain_from_regex(pattern)
                    if domain:
                        result["rules"].append({
                            "action": "reject",
                            "pattern": domain,
                            "type": "domain_suffix",
                            "source": "rewrite_local",
                        })
                    else:
                        result["skipped_unrepresentable"] += 1
                else:
                    result["skipped_unsupported"] += 1
            elif "script" in line.lower():
                result["skipped_scripts"] += 1
                m = re.search(r'https?://[^\s,]+', line)
                if m:
                    result["scripts"].append({"url": m.group(0)})
            else:
                result["skipped_unsupported"] += 1
        
        elif current_section == "filter_local":
            # Format: host-suffix, ads.example.com, reject
            # or: host, example.com, reject
            parts = [p.strip() for p in line.split(',')]
            if len(parts) >= 3:
                ftype, pattern, policy = parts[0].lower(), parts[1], parts[2].lower()
                if policy == "reject":
                    if ftype in ("host-suffix", "host"):
                        result["rules"].append({
                            "action": "reject",
                            "pattern": pattern,
                            "type": "domain_suffix",
                        })
                    elif ftype == "host-keyword":
                        result["rules"].append({
                            "action": "reject",
                            "pattern": pattern,
                            "type": "domain_keyword",
                        })
                    else:
                        result["skipped_unsupported"] += 1
                else:
                    result["skipped_routing"] += 1
            else:
                result["skipped_unsupported"] += 1
        
        elif current_section == "mitm":
            if "hostname" in line.lower():
                parts = line.split('=', 1)
                if len(parts) == 2:
                    hosts = [h.strip() for h in parts[1].split(',')]
                    hosts = [h for h in hosts if h and not h.startswith('%')]
                    result["hostnames"].extend(hosts)
    
    return result


def _extract_domain_from_regex(pattern: str) -> str | None:
    """Try to extract a domain from a URL regex pattern.
    
    Returns the domain or None if not extractable.
    """
    # Common patterns:
    # ^https?://(.*\.)?ads\.example\.com/ -> ads.example.com
    # .*\.ads\.com -> ads.com
    
    # Remove regex anchors and protocol
    p = pattern.strip('^$')
    p = re.sub(r'^https?\?://', '', p)
    # Remove common regex groups (best-effort, ignore errors)
    try:
        p = re.sub(r'\(\.\*\\\.\)\?', '', p)  # (.*\.)?
    except:
        pass
    p = p.replace('(.*)', '')
    p = p.replace('.*', '')
    
    # Look for domain-like pattern: xxx\.yyy\.zzz
    # Convert escaped dots to real dots
    p = p.replace('\\.', '.')
    
    # Extract the first domain-like substring
    m = re.search(r'([a-z0-9]([a-z0-9\-]*[a-z0-9])?\.)+[a-z]{2,}', p, re.IGNORECASE)
    if m:
        domain = m.group(0).lower()
        # Remove leading wildcard parts
        parts = domain.split('.')
        # If starts with something like "ads", keep it; this is best-effort
        return domain
    
    return None


def rules_to_domains(rules: list[dict]) -> list[str]:
    """Extract domains from parsed rules for sing-box block generation.
    
    Only includes reject rules with domain patterns.
    """
    domains = []
    for r in rules:
        if r.get("action") == "reject":
            pattern = r.get("pattern", "")
            rtype = r.get("type", "")
            if rtype in ("domain_suffix", "domain") and pattern:
                # Normalize: remove leading dot/wildcard
                d = pattern.lstrip('.').lstrip('*').lower()
                if d and d not in domains:
                    domains.append(d)
    return domains
