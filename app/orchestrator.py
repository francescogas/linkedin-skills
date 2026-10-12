"""Job queue, worker pool and scheduler: the part that runs around the clock.

- Jobs are rows in SQLite, so a restart loses nothing; `Store` re-queues what was
  running and `run_job` skips steps that already finished.
- A failing job retries with backoff (MAX_ATTEMPTS), then stops as `failed`.
- The scheduler turns due `schedules` rows into queued jobs.
- Nothing here publishes. Drafts land in the approval queue only.
"""
from __future__ import annotations

import re
import threading
import time
from typing import Optional

from . import llm, skills
from .store import Store
from .workflows import WORKFLOWS

MAX_ATTEMPTS = 3
BACKOFF_SECONDS = 30
URL_RE = re.compile(r"https?://[^\s]*linkedin\.com/[^\s]*")


def profile_block(p: Optional[dict]) -> str:
    if not p:
        return "(no profile selected)"
    rows = [("Name", p.get("name")), ("URL", p.get("url")), ("Role", p.get("role")),
            ("Goal", p.get("goal")), ("Audience", p.get("audience")), ("Voice notes", p.get("voice"))]
    text = "\n".join(f"{k}: {v}" for k, v in rows if v)
    if p.get("profile_text"):
        text += f"\n\nCurrent profile content:\n{p['profile_text']}"
    return text


def resolve_input(workflow: dict, raw: str) -> str:
    """Fetch a LinkedIn post through the Apify layer when a URL was given.

    Fetched text is wrapped as untrusted data (references/untrusted-content.md).
    No token or no network: the URL goes through as is and the agent works from
    what the user pasted around it.
    """
    raw = (raw or "").strip()
    if workflow["needs"] != "url" or not URL_RE.search(raw):
        return raw
    try:
        import lib
        post = lib.fetch_post(URL_RE.search(raw).group(0))
    except Exception:
        post = None
    if not post:
        return raw
    body = post.get("text") or post.get("content") or str(post)
    return f"{raw}\n<untrusted_content source=\"apify\">\n{body}\n</untrusted_content>"


def render(template: str, ctx: dict) -> str:
    def sub(m):
        key = m.group(1)
        if key.startswith("out."):
            return ctx["outs"].get(key[4:], "")
        return str(ctx.get(key, ""))
    return re.sub(r"\{([a-z_.]+)\}", sub, template)


class Orchestrator:
    def __init__(self, store: Store, workers: int = 2):
        self.store = store
        self.n_workers = workers
        self.stop = threading.Event()
        self.threads: list[threading.Thread] = []

    # ---- public API -------------------------------------------------------
    def enqueue(self, workflow: str, profile_id: Optional[int], input_text: str = "", schedule_id: Optional[int] = None) -> int:
        if workflow not in WORKFLOWS:
            raise KeyError(f"unknown workflow: {workflow}")
        now = time.time()
        return self.store.insert("jobs", workflow=workflow, profile_id=profile_id, input=input_text,
                                 status="queued", steps=[], schedule_id=schedule_id, created=now, updated=now)

    def start(self) -> None:
        for i in range(self.n_workers):
            t = threading.Thread(target=self._worker, name=f"worker-{i}", daemon=True)
            t.start()
            self.threads.append(t)
        t = threading.Thread(target=self._scheduler, name="scheduler", daemon=True)
        t.start()
        self.threads.append(t)

    def shutdown(self) -> None:
        self.stop.set()

    # ---- execution --------------------------------------------------------
    def run_job(self, job: dict) -> None:
        wf = WORKFLOWS[job["workflow"]]
        profile = self.store.get("profiles", job["profile_id"]) if job["profile_id"] else None
        done = list(job["steps"] or [])
        ctx = {"profile": profile_block(profile), "input": resolve_input(wf, job["input"]),
               "outs": {s["id"]: s["output"] for s in done}, "prev": done[-1]["output"] if done else ""}
        for step in wf["steps"][len(done):]:
            prompt = render(step["prompt"], ctx)
            text, backend = llm.complete(skills.system_prompt(step["skill"]), prompt)
            text = text.strip()
            done.append({"id": step["id"], "skill": step["skill"], "backend": backend, "output": text})
            ctx["outs"][step["id"]], ctx["prev"] = text, text
            self.store.update("jobs", job["id"], steps=done, updated=time.time())   # checkpoint
            if step.get("emit"):
                self._emit_draft(job, profile, step["emit"], text)
        self.store.update("jobs", job["id"], status="done", error=None, updated=time.time())

    def _emit_draft(self, job: dict, profile: Optional[dict], kind: str, text: str) -> None:
        m = URL_RE.search(job["input"] or "")
        now = time.time()
        self.store.insert("drafts", job_id=job["id"], profile_id=job["profile_id"], kind=kind, text=text,
                          target_url=m.group(0) if m else None, status="pending", created=now, updated=now)

    def _worker(self) -> None:
        while not self.stop.is_set():
            job = self.store.claim_job()
            if not job:
                self.stop.wait(1.0)
                continue
            try:
                self.run_job(job)
            except Exception as e:                      # retry with backoff, then give up
                attempts = job["attempts"] + 1
                failed = attempts >= MAX_ATTEMPTS
                self.store.update("jobs", job["id"], attempts=attempts, error=str(e)[:500],
                                  status="failed" if failed else "queued",
                                  run_after=time.time() + BACKOFF_SECONDS * attempts, updated=time.time())

    def tick_schedules(self, now: Optional[float] = None) -> int:
        now = now or time.time()
        n = 0
        for s in self.store.list("schedules", "enabled=1 AND next_run<=?", (now,), order="id"):
            self.enqueue(s["workflow"], s["profile_id"], s["input"] or "", schedule_id=s["id"])
            self.store.update("schedules", s["id"], next_run=now + s["every_minutes"] * 60)
            n += 1
        return n

    def _scheduler(self) -> None:
        while not self.stop.is_set():
            self.tick_schedules()
            self.stop.wait(30.0)
