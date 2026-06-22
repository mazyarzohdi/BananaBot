"""Utility helpers."""

import json
import re
import time
from datetime import datetime


def format_expiry(expiry_ms: int) -> str:
    if not expiry_ms:
        return "نامحدود"
    if expiry_ms < 0:
        days = abs(expiry_ms) // 86400000
        return f"On-Hold ({days} روز)"
    ts = expiry_ms // 1000
    if ts < int(time.time()):
        return "منقضی شده"
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def format_price(amount: int) -> str:
    return f"{amount:,}"


def parse_positive_int(text: str) -> int | None:
    try:
        val = int(text.replace(",", "").replace(" ", "").strip())
        return val if val > 0 else None
    except ValueError:
        return None


def parse_positive_float(text: str) -> float | None:
    try:
        val = float(text.replace(",", "").replace(" ", "").strip())
        return val if val > 0 else None
    except ValueError:
        return None


def load_config_links(sub: dict) -> list[str]:
    """Extract the list of per-inbound config links from a subscription row,
    falling back to the legacy single config_link column."""
    raw = sub.get("config_links")
    if raw:
        try:
            links = json.loads(raw)
            if links:
                return links
        except (json.JSONDecodeError, TypeError):
            pass
    return [sub["config_link"]] if sub.get("config_link") else []


def build_sub_link_template(sample_link: str) -> str:
    """Convert a sample subscription link copied from the panel into a
    reusable template, with the subId replaced by a {sub_id} placeholder.

    3x-ui serves subscription links from its own built-in micro-server
    (separate host/port/path from the admin API), so there is no API call
    that returns them — they must be built locally from a known pattern.

    Example:
        https://host:2090/sub/gfxgtbjp12wskgyw
        -> https://host:2090/sub/{sub_id}
    """
    sample_link = sample_link.strip()

    # Defensive: if the admin pasted a markdown link like [id](https://...),
    # extract the raw URL instead of failing.
    md_match = re.match(r"^\[[^\]]*\]\((https?://[^\s)]+)\)$", sample_link)
    if md_match:
        sample_link = md_match.group(1)

    if not sample_link.startswith("http://") and not sample_link.startswith("https://"):
        raise ValueError("لینک باید با http:// یا https:// شروع شود.")

    if "?" in sample_link:
        path_part, _, query_part = sample_link.partition("?")
        suffix = "?" + query_part
    else:
        path_part, suffix = sample_link, ""

    path_part = path_part.rstrip("/")
    base, _, sample_id = path_part.rpartition("/")
    if not base or not sample_id or "://" not in base:
        raise ValueError(
            "لینک نامعتبر است. لینک باید شبیه این باشد:\n"
            "https://domain:port/sub/SUBID"
        )

    return f"{base}/{{sub_id}}{suffix}"
