"""Terminal control for the running Studio service: profiles, workflows, drafts, approval.

Talks to the same HTTP API as the web UI (so there is one writer to the database).
Reads APP_HOST / APP_PORT / APP_TOKEN from the environment; `lstudio` loads them
from /etc/linkedin-studio.env.
"""
from __future__ import annotations

import argparse
import os
import sys
import time

import requests


class Ctl:
    def __init__(self, base: str, token: str | None, out=sys.stdout):
        self.base, self.out = base.rstrip("/"), out
        self.h = {"Authorization": f"Bearer {token}"} if token else {}

    def call(self, method: str, path: str, body: dict | None = None):
        r = requests.request(method, self.base + path, json=body, headers=self.h, timeout=30)
        data = r.json()
        if r.status_code >= 400:
            raise SystemExit(f"error {r.status_code}: {data.get('error', data)}")
        return data

    def p(self, *a):
        print(*a, file=self.out)

    def show_job(self, j: dict, full: bool = True):
        self.p(f"job #{j['id']} {j['workflow']}  status={j['status']}" + (f"  error={j['error']}" if j.get("error") else ""))
        if full:
            for s in j.get("steps") or []:
                self.p(f"\n--- {s['id']} ({s['skill']} via {s['backend']}) ---\n{s['output']}")

    def wait(self, jid: int, timeout: int) -> dict:
        end = time.time() + timeout
        while time.time() < end:
            j = self.call("GET", f"/api/jobs/{jid}")
            if j["status"] in ("done", "failed"):
                return j
            time.sleep(3)
        raise SystemExit(f"job #{jid} still running after {timeout}s; check later: lstudio job {jid}")


def text_arg(value: str | None, path: str | None) -> str:
    if path:
        with open(path, encoding="utf-8") as f:
            return f.read()
    return value or ""


def main(argv: list[str], ctl: Ctl, confirm=input) -> int:
    ap = argparse.ArgumentParser(prog="lstudio")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("workflows")
    pa = sub.add_parser("profile-add")
    pa.add_argument("name")
    for k in ("url", "role", "goal", "audience", "voice"):
        pa.add_argument(f"--{k}", default="")
    pa.add_argument("--text-file", help="file with the current profile text (headline, About, experience)")
    sub.add_parser("profiles")
    r = sub.add_parser("run")
    r.add_argument("workflow")
    r.add_argument("input", nargs="?", default="")
    r.add_argument("--input-file")
    r.add_argument("--profile", type=int)
    r.add_argument("--no-wait", action="store_true")
    r.add_argument("--timeout", type=int, default=900)
    sub.add_parser("jobs")
    j = sub.add_parser("job")
    j.add_argument("id", type=int)
    rt = sub.add_parser("retry")
    rt.add_argument("id", type=int)
    d = sub.add_parser("drafts")
    d.add_argument("--all", action="store_true")
    ap_ = sub.add_parser("approve")
    ap_.add_argument("id", type=int)
    ap_.add_argument("--edit-file", help="publish this text instead of the draft")
    ap_.add_argument("--at", help="schedule time, ISO 8601 UTC (posts only)")
    ap_.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    rj = sub.add_parser("reject")
    rj.add_argument("id", type=int)
    sc = sub.add_parser("schedules")
    sa = sub.add_parser("schedule-add")
    sa.add_argument("workflow")
    sa.add_argument("every_minutes", type=int)
    sa.add_argument("input", nargs="?", default="")
    sa.add_argument("--profile", type=int)
    sd = sub.add_parser("schedule-del")
    sd.add_argument("id", type=int)
    a = ap.parse_args(argv)
    P = ctl.p

    if a.cmd == "status":
        s = ctl.call("GET", "/api/status")
        P("models:", " > ".join(s["llm"]["chain"]), "| publish:", s["publish_backend"], "| read:", s["read_layer"])
    elif a.cmd == "workflows":
        for w in ctl.call("GET", "/api/workflows"):
            P(f"{w['id']:<18} {w['title']}: {w['about']}")
    elif a.cmd == "profile-add":
        body = {k: getattr(a, k) for k in ("name", "url", "role", "goal", "audience", "voice")}
        body["profile_text"] = text_arg(None, a.text_file)
        P("profile id:", ctl.call("POST", "/api/profiles", body)["id"])
    elif a.cmd == "profiles":
        for x in ctl.call("GET", "/api/profiles"):
            P(f"#{x['id']}  {x['name']}  {x.get('role') or ''}")
    elif a.cmd == "run":
        jid = ctl.call("POST", "/api/jobs", {"workflow": a.workflow, "profile_id": a.profile,
                                             "input": text_arg(a.input, a.input_file)})["id"]
        P(f"queued job #{jid}")
        if not a.no_wait:
            ctl.show_job(ctl.wait(jid, a.timeout))
            if any(x["job_id"] == jid and x["status"] == "pending" for x in ctl.call("GET", "/api/drafts")):
                P("\nDrafts waiting: lstudio drafts")
    elif a.cmd == "jobs":
        for x in ctl.call("GET", "/api/jobs"):
            ctl.show_job(x, full=False)
    elif a.cmd == "job":
        ctl.show_job(ctl.call("GET", f"/api/jobs/{a.id}"))
    elif a.cmd == "retry":
        ctl.call("POST", f"/api/jobs/{a.id}/retry")
        P("requeued")
    elif a.cmd == "drafts":
        rows = [x for x in ctl.call("GET", "/api/drafts") if a.all or x["status"] == "pending"]
        for x in rows:
            P(f"\n=== draft #{x['id']} [{x['kind']}] {x['status']}  target: {x['target_url'] or 'new post'}  ({len(x['text'])} chars)\n{x['text']}")
        if not rows:
            P("no pending drafts")
    elif a.cmd == "approve":
        if not a.yes and confirm(f"Publish draft #{a.id} now? Type 'yes': ").strip().lower() != "yes":
            P("not published")
            return 1
        body = {"text": text_arg(None, a.edit_file) or None, "scheduled_time": a.at}
        res = ctl.call("POST", f"/api/drafts/{a.id}/approve", body)
        P("published via", res["backend"])
        if res["backend"] == "manual":
            P(res["result"]["message"])
    elif a.cmd == "reject":
        ctl.call("POST", f"/api/drafts/{a.id}/reject")
        P("rejected")
    elif a.cmd == "schedules":
        for x in ctl.call("GET", "/api/schedules"):
            P(f"#{x['id']} {x['workflow']} every {x['every_minutes']} min, next {time.strftime('%Y-%m-%d %H:%M', time.localtime(x['next_run']))}")
    elif a.cmd == "schedule-add":
        P("schedule id:", ctl.call("POST", "/api/schedules", {"workflow": a.workflow, "every_minutes": a.every_minutes,
                                                             "input": a.input, "profile_id": a.profile})["id"])
    elif a.cmd == "schedule-del":
        ctl.call("DELETE", f"/api/schedules/{a.id}")
        P("deleted")
    return 0


def cli() -> None:
    host, port = os.getenv("APP_HOST", "127.0.0.1"), os.getenv("APP_PORT", "8765")
    ctl = Ctl(f"http://{'127.0.0.1' if host in ('0.0.0.0', '::') else host}:{port}", os.getenv("APP_TOKEN"))
    sys.exit(main(sys.argv[1:], ctl))
