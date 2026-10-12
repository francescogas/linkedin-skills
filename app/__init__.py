"""LinkedIn Skills Studio: a local-first multi-agent app on top of the 12 skills.

The skills in `skills/` are instruction files. This package turns each one into
an agent (SKILL.md as the system prompt), chains agents into workflows, runs
them from a persistent queue around the clock, and puts every outbound action
behind a human approval gate before `lib.publish` is called.
"""
