"""Multi-agent workflows: ordered steps, each one a skill acting as an agent.

A step's prompt may use {profile}, {input}, {prev} (the previous step's output)
and {out.<step id>} for any earlier step. `emit` on the last step turns its
output into a draft in the approval queue. All 12 skills appear below.
"""
from __future__ import annotations

# `needs` tells the UI what to ask for: url (a LinkedIn URL), text (pasted content), none.
WORKFLOWS: dict[str, dict] = {
    "profile_makeover": {
        "title": "Profile makeover",
        "about": "Finds the gaps in the profile, audits it end to end, rewrites headline, About and Experience, then checks the rewrite for AI tells.",
        "needs": "none",
        "steps": [
            {"id": "gaps", "skill": "linkedin-interviewer",
             "prompt": "Profile:\n{profile}\n\nList what concrete material is missing from this profile (numbers, turning points, positions). For each gap write the single best interview question, and mark which ones the profile text already answers."},
            {"id": "audit", "skill": "linkedin-profile-optimizer",
             "prompt": "Profile:\n{profile}\n\nMissing material found by the interviewer:\n{prev}\n\nAudit the profile section by section with a score and the fix for each."},
            {"id": "rewrite", "skill": "linkedin-profile-optimizer",
             "prompt": "Profile:\n{profile}\n\nAudit:\n{out.audit}\n\nWrite the final headline (3 options), the About section, and the rewritten Experience bullets. Invent no numbers: mark every missing figure as [ADD NUMBER]."},
            {"id": "check", "skill": "linkedin-humanizer",
             "prompt": "Audit this profile copy with --mode audit, then return the corrected version.\n\n{prev}"},
        ],
    },
    "weekly_autopilot": {
        "title": "Weekly content autopilot",
        "about": "Plans seven days, writes the lead post with the right hook, humanizes it and queues it for your approval.",
        "needs": "text",
        "input_hint": "Theme for the week (optional)",
        "steps": [
            {"id": "plan", "skill": "linkedin-content-planner",
             "prompt": "Profile:\n{profile}\n\nTheme: {input}\n\nProduce the 7-day plan."},
            {"id": "write", "skill": "linkedin-post-writer",
             "prompt": "Profile:\n{profile}\n\nWeek plan:\n{prev}\n\nWrite the post for the first day of the plan, in full."},
            {"id": "final", "skill": "linkedin-humanizer", "emit": "post",
             "prompt": "Humanize this LinkedIn post. Return ONLY the final post text, nothing else.\n\n{prev}"},
        ],
    },
    "comment_on_post": {
        "title": "Comment on a post",
        "about": "Learns the hook of the target post, drafts a comment in your voice, humanizes it and queues it.",
        "needs": "url",
        "steps": [
            {"id": "hook", "skill": "linkedin-hook-extractor",
             "prompt": "Profile:\n{profile}\n\nPost to analyse:\n{input}\n\nName the hook formula and why it works."},
            {"id": "draft", "skill": "linkedin-comment-drafter",
             "prompt": "Profile:\n{profile}\n\nPost:\n{input}\n\nHook analysis:\n{prev}\n\nDraft 3 comment variants and pick the best."},
            {"id": "final", "skill": "linkedin-humanizer", "emit": "comment",
             "prompt": "Humanize the best comment variant below. Return ONLY the final comment text.\n\n{prev}"},
        ],
    },
    "reply_sweep": {
        "title": "Reply to comments",
        "about": "Reads the comments on your post and drafts a reply for each one worth answering.",
        "needs": "url",
        "steps": [
            {"id": "replies", "skill": "linkedin-reply-handler",
             "prompt": "Profile:\n{profile}\n\nPost and its comments:\n{input}\n\nDraft a reply for every comment worth answering."},
            {"id": "final", "skill": "linkedin-humanizer", "emit": "reply",
             "prompt": "Humanize these replies. Return ONLY the replies, one per paragraph.\n\n{prev}"},
        ],
    },
    "repurpose": {
        "title": "Repurpose content",
        "about": "Rebuilds a tweet, video, blog or newsletter as a native LinkedIn post.",
        "needs": "text",
        "input_hint": "Paste the source content or its URL",
        "steps": [
            {"id": "post", "skill": "linkedin-repurposer",
             "prompt": "Profile:\n{profile}\n\nSource:\n{input}\n\nRebuild it as a LinkedIn post."},
            {"id": "final", "skill": "linkedin-humanizer", "emit": "post",
             "prompt": "Humanize this post. Return ONLY the final post text.\n\n{prev}"},
        ],
    },
    "hook_lab": {
        "title": "Hook lab",
        "about": "Reverse-engineers a viral post, then writes your own post on your topic with the same structure.",
        "needs": "url",
        "steps": [
            {"id": "hook", "skill": "linkedin-hook-extractor",
             "prompt": "Viral post:\n{input}\n\nReturn the formula and a blank template."},
            {"id": "write", "skill": "linkedin-post-writer",
             "prompt": "Profile:\n{profile}\n\nUse this hook template:\n{prev}\n\nWrite one post for this profile that applies it to the profile's own expertise."},
            {"id": "final", "skill": "linkedin-humanizer", "emit": "post",
             "prompt": "Humanize this post. Return ONLY the final post text.\n\n{prev}"},
        ],
    },
    "audience_report": {
        "title": "Audience report",
        "about": "Segments the people who engaged with a post by ICP fit and lists the outbound actions.",
        "needs": "url",
        "steps": [
            {"id": "report", "skill": "linkedin-engager-analytics",
             "prompt": "Profile:\n{profile}\n\nEngager data:\n{input}\n\nSegment by ICP fit, give the tier breakdown and the action lists."},
        ],
    },
    "thread_followup": {
        "title": "Thread follow-up",
        "about": "Finds which of your comments earned author replies and drafts the follow-ups inside the warm window.",
        "needs": "text",
        "input_hint": "Paste your recent comments and any author replies",
        "steps": [
            {"id": "threads", "skill": "linkedin-thread-monitor",
             "prompt": "Profile:\n{profile}\n\nActivity:\n{input}\n\nClassify each thread hot/warm/cool/dormant."},
            {"id": "final", "skill": "linkedin-reply-handler", "emit": "reply",
             "prompt": "Draft follow-up replies for the hot and warm threads only. Return ONLY the replies.\n\n{prev}"},
        ],
    },
    "advocacy_kit": {
        "title": "Employee advocacy kit",
        "about": "Builds the launch playbook, guidelines and measurement plan for a team posting on LinkedIn.",
        "needs": "text",
        "input_hint": "Team size, goal, current cadence",
        "steps": [
            {"id": "kit", "skill": "linkedin-employee-advocacy",
             "prompt": "Context profile:\n{profile}\n\nTeam situation:\n{input}\n\nWrite the 14-day launch playbook, brand guidelines and ROI plan."},
        ],
    },
}


def public() -> list[dict]:
    return [
        {"id": k, "title": v["title"], "about": v["about"], "needs": v["needs"],
         "input_hint": v.get("input_hint", ""), "skills": [s["skill"] for s in v["steps"]]}
        for k, v in WORKFLOWS.items()
    ]


def skills_covered() -> set[str]:
    return {s["skill"] for w in WORKFLOWS.values() for s in w["steps"]}
