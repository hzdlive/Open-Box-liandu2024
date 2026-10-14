"""OpenBox-OSS core: subscription parsing -> node model -> sing-box config.

Clean-room implementation. Standard library only.
"""

from .models import AppConfig, DnsConfig, Node, SiteSet
from .singbox import build_config
from .subscription import parse_subscription

__all__ = ["AppConfig", "DnsConfig", "Node", "SiteSet", "build_config", "parse_subscription"]
