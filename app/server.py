"""HTTP API + web UI. Standard library only; no build step.

Binds to 127.0.0.1 by default. To expose it (private cloud, a team), set
APP_HOST and APP_TOKEN: a non-loopback bind without a token is refused.
"""
from __future__ import annotations

import hmac
import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from . import llm, publishing, skills, workflows
from .orchestrator import Orchestrator
from .store import Store

STATIC = Path(__file__).parent / "static"
PROFILE_FIELDS = ("name", "url", "role", "goal", "audience", "voice", "profile_text")


def make_handler(store: Store, orch: Orchestrator, token: str | None):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):  # quiet
            pass

        def _send(self, code: int, body, ctype="application/json"):
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def _authed(self) -> bool:
            if not token:
                return True
            got = self.headers.get("Authorization", "").removeprefix("Bearer ")
            return hmac.compare_digest(got, token)

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n) or b"{}") if n else {}

        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/":
                return self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
            if not self._authed():
                return self._send(401, {"error": "unauthorized"})
            self._route("GET", path)

        def do_POST(self):
            if not self._authed():
                return self._send(401, {"error": "unauthorized"})
            self._route("POST", urlparse(self.path).path)

        def do_DELETE(self):
            if not self._authed():
                return self._send(401, {"error": "unauthorized"})
            self._route("DELETE", urlparse(self.path).path)

        def _route(self, method: str, path: str):
            try:
                self._send(*self._dispatch(method, path))
            except KeyError as e:
                self._send(404, {"error": str(e)})
            except (ValueError, json.JSONDecodeError) as e:
                self._send(400, {"error": str(e)})
            except Exception as e:
                self._send(500, {"error": f"{type(e).__name__}: {e}"})

        def _dispatch(self, method: str, path: str):
            import lib
            if method == "GET":
                if path == "/api/status":
                    return 200, {"llm": llm.describe(), "publish_backend": lib.active_backend(),
                                 "image_backend": lib.image_backend(),
                                 "read_layer": "apify" if os.getenv("APIFY_TOKEN") else "paste"}
                if path == "/api/skills":
                    return 200, skills.list_skills()
                if path == "/api/workflows":
                    return 200, workflows.public()
                if path == "/api/profiles":
                    return 200, store.list("profiles")
                if path == "/api/jobs":
                    return 200, store.list("jobs")
                if m := re.fullmatch(r"/api/jobs/(\d+)", path):
                    j = store.get("jobs", int(m[1]))
                    if not j:
                        raise KeyError("job not found")
                    return 200, j
                if path == "/api/drafts":
                    return 200, store.list("drafts")
                if path == "/api/schedules":
                    return 200, store.list("schedules")
            if method == "POST":
                b = self._body()
                if path == "/api/profiles":
                    vals = {k: str(b.get(k, "")) for k in PROFILE_FIELDS}
                    if not vals["name"].strip():
                        raise ValueError("name is required")
                    import time
                    return 201, {"id": store.insert("profiles", created=time.time(), **vals)}
                if path == "/api/jobs":
                    pid = int(b["profile_id"]) if b.get("profile_id") else None
                    return 201, {"id": orch.enqueue(b["workflow"], pid, b.get("input", ""))}
                if path == "/api/schedules":
                    import time
                    minutes = int(b["every_minutes"])
                    if minutes < 1:
                        raise ValueError("every_minutes must be >= 1")
                    if b["workflow"] not in workflows.WORKFLOWS:
                        raise KeyError(f"unknown workflow: {b['workflow']}")
                    sid = store.insert("schedules", workflow=b["workflow"], profile_id=int(b["profile_id"]) if b.get("profile_id") else None,
                                       input=b.get("input", ""), every_minutes=minutes, next_run=time.time() + minutes * 60)
                    return 201, {"id": sid}
                if m := re.fullmatch(r"/api/drafts/(\d+)/(approve|reject)", path):
                    did = int(m[1])
                    if m[2] == "approve":
                        return 200, publishing.approve(store, did, b.get("text"))
                    publishing.reject(store, did)
                    return 200, {"ok": True}
                if m := re.fullmatch(r"/api/jobs/(\d+)/retry", path):
                    if not store.get("jobs", int(m[1])):
                        raise KeyError("job not found")
                    store.update("jobs", int(m[1]), status="queued", attempts=0, run_after=0, error=None)
                    return 200, {"ok": True}
            if method == "DELETE":
                if m := re.fullmatch(r"/api/schedules/(\d+)", path):
                    store.delete("schedules", int(m[1]))
                    return 200, {"ok": True}
                if m := re.fullmatch(r"/api/profiles/(\d+)", path):
                    store.delete("profiles", int(m[1]))
                    return 200, {"ok": True}
            raise KeyError(f"no route: {method} {path}")

    return H


def serve(host: str | None = None, port: int | None = None, workers: int = 2) -> None:
    host = host or os.getenv("APP_HOST", "127.0.0.1")
    port = port or int(os.getenv("APP_PORT", "8765"))
    token = os.getenv("APP_TOKEN") or None
    if host not in ("127.0.0.1", "localhost", "::1") and not token:
        raise SystemExit("Refusing to bind a non-loopback address without APP_TOKEN set.")
    store = Store()
    orch = Orchestrator(store, workers=workers)
    orch.start()
    srv = ThreadingHTTPServer((host, port), make_handler(store, orch, token))
    print(f"LinkedIn Skills Studio on http://{host}:{port}  (LLM chain: {llm.chain()})")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        orch.shutdown()
