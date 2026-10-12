"""The approval gate. The only module that calls `lib.publish`, and only for an approved draft."""
from __future__ import annotations

import time

from .store import Store


def approve(store: Store, draft_id: int, text: str | None = None) -> dict:
    d = store.get("drafts", draft_id)
    if not d:
        raise KeyError("draft not found")
    if d["status"] != "pending":
        raise ValueError(f"draft is {d['status']}, not pending")
    body = (text if text is not None else d["text"]).strip()
    if not body:
        raise ValueError("empty draft")
    import lib
    kind, url = d["kind"], d["target_url"] or ""
    kwargs = {}
    if kind in ("comment", "reply"):
        parsed = lib.parse_linkedin_url(url)
        if not parsed["post_urn"]:
            raise ValueError(f"a {kind} needs a LinkedIn post URL as target, got {url!r}")
        kwargs["post_urn"] = parsed["post_urn"]
        if kind == "reply":
            kwargs["parent_comment"] = parsed["comment_urn"]
    result = lib.publish(kind, body, url or "https://www.linkedin.com/feed/", **kwargs)
    store.update("drafts", draft_id, text=body, status="approved", result=result, updated=time.time())
    return {"draft": store.get("drafts", draft_id), "backend": lib.active_backend(), "result": result}


def reject(store: Store, draft_id: int) -> None:
    store.update("drafts", draft_id, status="rejected", updated=time.time())
