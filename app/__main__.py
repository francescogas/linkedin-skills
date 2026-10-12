"""python -m app [serve|worker|run <workflow> [input]]"""
import argparse
import sys
import time

from . import server
from .orchestrator import Orchestrator
from .store import Store
from .workflows import WORKFLOWS


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m app")
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("serve", help="web UI + API + background workers (default)")
    s.add_argument("--host"); s.add_argument("--port", type=int); s.add_argument("--workers", type=int, default=2)
    w = sub.add_parser("worker", help="headless 24/7 mode: queue and scheduler only, no web server")
    w.add_argument("--workers", type=int, default=2)
    r = sub.add_parser("run", help="run one workflow now and print each agent's output")
    r.add_argument("workflow", choices=sorted(WORKFLOWS)); r.add_argument("input", nargs="?", default="")
    r.add_argument("--profile", type=int)
    a = ap.parse_args()
    if a.cmd in (None, "serve"):
        server.serve(getattr(a, "host", None), getattr(a, "port", None), getattr(a, "workers", 2))
    elif a.cmd == "worker":
        o = Orchestrator(Store(), workers=a.workers); o.start()
        print("worker running; Ctrl-C to stop")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            o.shutdown()
    else:
        st = Store(); o = Orchestrator(st)
        jid = o.enqueue(a.workflow, a.profile, a.input)
        o.run_job(st.get("jobs", jid))
        for step in st.get("jobs", jid)["steps"]:
            print(f"\n=== {step['id']} ({step['skill']} via {step['backend']}) ===\n{step['output']}")
        print(f"\n{len(st.list('drafts', 'job_id=?', (jid,)))} draft(s) waiting in the approval queue.")


if __name__ == "__main__":
    sys.exit(main())
