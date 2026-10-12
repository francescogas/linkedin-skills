# LinkedIn Skills Studio

A local-first app that runs all 12 skills as cooperating agents to improve and automate one or more LinkedIn profiles. Nothing is published without your approval.

```bash
pip install -r requirements.txt
python3 -m app                 # web UI on http://127.0.0.1:8765, plus background workers
python3 -m app worker          # headless 24/7 mode (queue + scheduler, no web server)
python3 -m app run profile_makeover --profile 1    # one workflow from the terminal
```

## How it works

| Piece | What it does |
|---|---|
| `skills.py` | Loads each `skills/*/SKILL.md` (plus `references/voice-rules.md`) as an agent's system prompt |
| `workflows.py` | 9 workflows chain agents; every skill is used at least once |
| `orchestrator.py` | SQLite job queue, worker pool, retries with backoff, scheduler, crash-safe resume (finished steps are kept) |
| `publishing.py` | The only code that calls `lib.publish`, and only for a draft you approved |
| `server.py` + `static/` | JSON API and a single-page UI |

| Workflow | Agents (skills) |
|---|---|
| Profile makeover | interviewer → profile-optimizer → profile-optimizer → humanizer |
| Weekly content autopilot | content-planner → post-writer → humanizer → **draft** |
| Comment on a post | hook-extractor → comment-drafter → humanizer → **draft** |
| Reply to comments | reply-handler → humanizer → **drafts** |
| Repurpose content | repurposer → humanizer → **draft** |
| Hook lab | hook-extractor → post-writer → humanizer → **draft** |
| Audience report | engager-analytics |
| Thread follow-up | thread-monitor → reply-handler → **drafts** |
| Employee advocacy kit | employee-advocacy |

Schedules (Pianificazioni tab) enqueue a workflow every N minutes, so a weekly autopilot fills the approval queue while you are away.

## Models: cloud, private cloud, local, offline

Set `LLM_CHAIN` (comma list, tried in order) or let it follow what is configured.

| Mode | Settings |
|---|---|
| Anthropic API | `ANTHROPIC_API_KEY`, optional `ANTHROPIC_MODEL` |
| Private cloud | `ANTHROPIC_BASE_URL` pointing at your Messages-API gateway |
| Local / air-gapped | `LLM_BASE_URL` (Ollama, LM Studio, vLLM; OpenAI-compatible), `LLM_MODEL` |
| Cloud with local fallback | `LLM_CHAIN=anthropic,local` (a dropped network falls through to the local model) |
| Nothing set | `offline` placeholder, so the whole pipeline still runs |

Reading LinkedIn posts uses Apify when `APIFY_TOKEN` is set, otherwise paste the text. Publishing uses Publora when configured, otherwise the approval card returns a copy-paste block (see the root `.env.example`).

## Data, images and scheduling

- With `APIFY_TOKEN`, the post, comment, engager and recent-comment workflows fetch their input from a LinkedIn URL (`sources.py`); without it, paste the text. Fetched data is fenced as untrusted and capped at 12k characters.
- A pending post draft can get an image (`PIXFARO_TOKEN`, otherwise you get the prompt to run yourself) and a publish time; both go to Publora on approval.

## Running it around the clock

- State lives in `app/data/studio.db` (override with `LINKEDIN_APP_DATA`). A restart re-queues running jobs and resumes after the last finished step.
- To serve beyond localhost set `APP_HOST` and `APP_TOKEN`; a non-loopback bind without a token is refused. Put TLS in front of it.
- Run `python3 -m app worker` under systemd or `launchd`, or use the bundled `Dockerfile` and `docker-compose.yml` (`APP_TOKEN=... docker compose up -d`; state lives in the `studio-data` volume; keep TLS in a reverse proxy in front).

## Safety

Fetched LinkedIn content is wrapped as `<untrusted_content>` and agents are told to treat it as data (`references/untrusted-content.md`). Agents have no tools; the approval endpoint is the single publish path, and a draft can be approved once.
