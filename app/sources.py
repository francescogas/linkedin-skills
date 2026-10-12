"""Read layer for workflows: pull LinkedIn data through Apify when a token is set.

Everything fetched is wrapped as <untrusted_content> (references/untrusted-content.md)
and truncated, so a hostile post cannot steer an agent or blow the context window.
Without a token, or on any failure, callers get None and the pasted text is used.
"""
from __future__ import annotations

import json
import os
import re
from typing import Optional

MAX_CHARS = 12000
URL_RE = re.compile(r"https?://[^\s]*linkedin\.com/[^\s]*")
HANDLE_RE = re.compile(r"linkedin\.com/in/([^/?\s#]+)")


def wrap(kind: str, data) -> str:
    body = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, default=str)
    body = body.replace("</untrusted_content>", "")[:MAX_CHARS]
    return f'<untrusted_content source="apify" kind="{kind}">\n{body}\n</untrusted_content>'


def _client():
    from lib.apify_client import ApifyClient
    return ApifyClient()


def fetch(mode: str, raw: str, profile_url: Optional[str] = None) -> Optional[str]:
    """mode: post | comments | engagers | my_comments. Returns wrapped text or None."""
    if not os.getenv("APIFY_TOKEN"):
        return None
    m = URL_RE.search(raw or "")
    try:
        if mode == "post" and m:
            import lib
            post = lib.fetch_post(m.group(0))
            return wrap("post", post) if post else None
        if mode == "comments" and m:
            import lib
            post = lib.fetch_post(m.group(0)) or {}
            comments = _client().fetch_post_comments(post_id=m.group(0), max_items=40, scrape_replies=True)
            return wrap("post+comments", {"post": post, "comments": comments})
        if mode == "engagers" and m:
            return wrap("engagers", _client().fetch_post_engagers(post_url=m.group(0), max_items=100))
        if mode == "my_comments":
            h = HANDLE_RE.search(raw or "") or HANDLE_RE.search(profile_url or "")
            handle = h.group(1) if h else (raw or "").strip()
            if not handle or " " in handle:
                return None
            return wrap("my_comments", _client().fetch_user_recent_comments(username=handle, result_limit=30))
    except Exception:
        return None
    return None
